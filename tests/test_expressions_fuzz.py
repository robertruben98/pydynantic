"""Property-based fuzzing of the expression builder.

Generates arbitrary attribute paths (including dotted paths, reserved words,
and weird characters) and arbitrary condition trees, compiles them against a
fresh :class:`ExpressionContext`, and asserts structural invariants of the
placeholder allocation and the compiled expression string.
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pydynantic import F
from pydynantic.expressions import Condition, ExpressionContext

# A sample of DynamoDB reserved words. These must never appear as bare tokens
# in a compiled expression; they may only be referenced through ``#nK`` aliases.
RESERVED_WORDS: list[str] = [
    "status",
    "size",
    "name",
    "ttl",
    "type",
    "count",
    "value",
    "data",
    "timestamp",
    "user",
    "order",
    "group",
    "key",
]

# Structural tokens the compiler itself emits (operators / keywords / functions).
# Used to distinguish builder-emitted text from leaked raw attribute content.
_STRUCTURAL_TOKENS: frozenset[str] = frozenset(
    {
        "=",
        "<>",
        "<",
        "<=",
        ">",
        ">=",
        "BETWEEN",
        "AND",
        "OR",
        "NOT",
        "IN",
        "begins_with",
        "contains",
        "attribute_exists",
        "attribute_not_exists",
        "attribute_type",
    }
)

# A token in a compiled expression is "clean" if it is a name alias, a value
# alias, or a structural keyword/function emitted by the builder.
_NAME_TOKEN = re.compile(r"^#n\d+$")
_VALUE_TOKEN = re.compile(r"^:v\d+$")
# Split the compiled expression on whitespace and the punctuation the builder
# emits: ``(``, ``)``, ``,`` and ``.`` (the dotted-path separator between alias
# tokens). Whatever remains must be a clean token.
_TOKEN_SPLIT = re.compile(r"[\s(),.]+")


def _is_clean_token(token: str) -> bool:
    if token == "":
        return True
    return bool(_NAME_TOKEN.match(token) or _VALUE_TOKEN.match(token)) or (
        token in _STRUCTURAL_TOKENS
    )


# A single path segment: ASCII word chars, spaces, hyphens, leading digits, and
# a sprinkling of unicode. Crucially it must NOT contain ``.`` (the path
# separator) and must be non-empty so ``split(".")`` yields no empty segments.
_segment_chars = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_ -áéíóúñüßΩλ漢字",
        blacklist_characters=".",
    ),
    min_size=1,
    max_size=8,
).filter(lambda s: "." not in s and s.strip(" ") != "")

#: A single path segment, biased towards reserved words and odd inputs.
segments: st.SearchStrategy[str] = st.one_of(
    st.sampled_from(RESERVED_WORDS),
    _segment_chars,
)

#: An attribute name: 1-3 segments joined by ``.`` to form a dotted path.
attr_names: st.SearchStrategy[str] = st.lists(segments, min_size=1, max_size=3).map(
    lambda parts: ".".join(parts)
)

#: Leaf values are kept to strings so marshalling is always valid.
leaf_values: st.SearchStrategy[str] = st.text(max_size=12)

#: DynamoDB attribute-type codes accepted by ``attribute_type``.
type_codes: st.SearchStrategy[str] = st.sampled_from(
    ["S", "SS", "N", "NS", "B", "BS", "BOOL", "NULL", "L", "M"]
)


def _leaf_conditions() -> st.SearchStrategy[Condition]:
    """Strategy producing a single (non-composite) condition."""
    fields = attr_names.map(F)
    return st.one_of(
        st.builds(lambda f, v: f == v, fields, leaf_values),
        st.builds(lambda f, lo, hi: f.between(lo, hi), fields, leaf_values, leaf_values),
        st.builds(lambda f, p: f.begins_with(p), fields, leaf_values),
        st.builds(
            lambda f, vs: f.is_in(vs),
            fields,
            st.lists(leaf_values, min_size=1, max_size=4),
        ),
        st.builds(lambda f, t: f.is_type(t), fields, type_codes),
    )


#: A recursive condition tree composing leaves with ``&``, ``|`` and ``~``.
conditions: st.SearchStrategy[Condition] = st.recursive(
    _leaf_conditions(),
    lambda children: st.one_of(
        st.builds(lambda a, b: a & b, children, children),
        st.builds(lambda a, b: a | b, children, children),
        st.builds(lambda c: ~c, children),
    ),
    max_leaves=12,
)

_FUZZ_SETTINGS = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@_FUZZ_SETTINGS
@given(name=attr_names)
def test_dedup_one_placeholder_per_segment(name: str) -> None:
    """INVARIANT 1: each distinct segment maps to exactly one ``#nK`` and
    re-registering a segment returns the same placeholder."""
    ctx = ExpressionContext()
    first = ctx.name(name)
    second = ctx.name(name)
    # Re-registering the same path yields an identical rendering (no new aliases).
    assert first == second
    # Segment values are unique: the placeholder->segment map is a bijection.
    assert len(set(ctx.names.values())) == len(ctx.names)
    # Every distinct segment of the path has exactly one alias.
    distinct_segments = set(name.split("."))
    assert len(ctx.names) == len(distinct_segments)
    assert set(ctx.names.values()) == distinct_segments


@_FUZZ_SETTINGS
@given(a=attr_names, b=attr_names)
def test_dedup_shared_segments_reused(a: str, b: str) -> None:
    """INVARIANT 1 (cross-path): a shared segment string reuses its alias."""
    ctx = ExpressionContext()
    ctx.name(a)
    ctx.name(b)
    assert len(set(ctx.names.values())) == len(ctx.names)
    assert set(ctx.names.values()) == set(a.split(".")) | set(b.split("."))


@_FUZZ_SETTINGS
@given(condition=conditions)
def test_round_trip_tokens_resolve(condition: Condition) -> None:
    """INVARIANT 2: every ``#nK`` / ``:vK`` token in the expression resolves."""
    ctx = ExpressionContext()
    expr = condition.compile(ctx)
    name_tokens = set(re.findall(r"#n\d+", expr))
    value_tokens = set(re.findall(r":v\d+", expr))
    for token in name_tokens:
        assert token in ctx.names
        assert isinstance(ctx.names[token], str)
    for token in value_tokens:
        assert token in ctx.values
        av = ctx.values[token]
        assert isinstance(av, dict) and len(av) == 1
        ((type_code, _),) = av.items()
        assert type_code in {"S", "N", "B", "BOOL", "NULL", "L", "M", "SS", "NS", "BS"}


@_FUZZ_SETTINGS
@given(condition=conditions)
def test_namespace_disjoint(condition: Condition) -> None:
    """INVARIANT 5: name and value placeholder namespaces never overlap."""
    ctx = ExpressionContext()
    condition.compile(ctx)
    assert set(ctx.names) & set(ctx.values) == set()


@_FUZZ_SETTINGS
@given(parts=st.lists(segments, min_size=1, max_size=3))
def test_dotted_path_alias_structure(parts: list[str]) -> None:
    """INVARIANT 3: ``a.b.c`` compiles to exactly len(parts) alias tokens joined
    by ``.``; no stored segment value contains a literal ``.``."""
    path = ".".join(parts)
    ctx = ExpressionContext()
    rendered = ctx.name(path)
    alias_tokens = rendered.split(".")
    assert len(alias_tokens) == len(parts)
    for token in alias_tokens:
        assert _NAME_TOKEN.match(token), token
    # Splitting must not have produced a stored segment containing ``.``.
    for raw_segment in ctx.names.values():
        assert "." not in raw_segment


@_FUZZ_SETTINGS
@given(
    word=st.sampled_from(RESERVED_WORDS),
    other=leaf_values,
)
def test_reserved_word_never_bare(word: str, other: str) -> None:
    """INVARIANT 4: a reserved word used as an attribute never appears as a bare
    token in the compiled expression -- only behind a ``#nK`` alias."""
    ctx = ExpressionContext()
    expr = (F(word) == other).compile(ctx)
    # The reserved word lives in the names map behind an alias.
    assert word in ctx.names.values()
    # It must not survive as a standalone token in the expression text.
    tokens = [t for t in _TOKEN_SPLIT.split(expr) if t]
    assert word not in tokens


@_FUZZ_SETTINGS
@given(condition=conditions)
def test_no_raw_special_chars_leak(condition: Condition) -> None:
    """INVARIANT 6: weird-char segments are carried verbatim in ``ctx.names``
    values, while the compiled expression contains only placeholders, operators,
    keywords and whitespace -- no raw special characters leak through."""
    ctx = ExpressionContext()
    expr = condition.compile(ctx)
    # Every token in the expression is a clean alias/keyword/structural token.
    for token in _TOKEN_SPLIT.split(expr):
        assert _is_clean_token(token), f"leaked token {token!r} in {expr!r}"
    # The raw (possibly weird) segments are preserved verbatim in the names map.
    for raw_segment in ctx.names.values():
        assert isinstance(raw_segment, str)
        assert "." not in raw_segment
