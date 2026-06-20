"""Property-based tests for :mod:`pydynantic.keys` render/parse symmetry.

``keys.parse(template, keys.render(template, attrs)) == attrs`` only holds when
the template has unambiguous literal separators between placeholders and the
attribute values do not themselves contain those separators. The strategies here
construct exactly that well-behaved space:

* templates of the form ``"PREFIX0{a0}SEP1{a1}SEP2{a2}..."`` where every literal
  segment is a non-empty run of separator characters (``#``/``/``) so adjacent
  placeholders are always separated by a literal the values cannot contain;
* attribute values that are non-empty strings drawn from an alphabet that
  excludes every separator character.

Three properties are asserted:

1. ``template_fields(template)`` returns exactly the placeholder names, in order.
2. ``parse(template, render(template, attrs)) == attrs`` for the well-behaved
   space above.
3. ``render`` raises :class:`KeyTemplateError` when a referenced attribute is
   missing or ``None``.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pydynantic.errors import KeyTemplateError
from pydynantic.keys import parse, render, template_fields

_SETTINGS = settings(max_examples=200, deadline=None)

# Separators used as literal glue between placeholders. The non-greedy regex in
# ``parse`` needs a literal boundary it can lock onto; values must never contain
# these characters.
_SEPARATORS = "#/"

# Attribute values: non-empty, and free of any separator character (and of the
# brace characters that delimit placeholders) so parsing is unambiguous. Control
# characters (incl. newlines) are excluded because ``parse``'s regex ``.`` does
# not match newlines, which would break round-trips for otherwise-valid strings.
_value_alphabet = st.characters(
    blacklist_characters=_SEPARATORS + "{}",
    blacklist_categories=("Cs", "Cc"),
)
values = st.text(alphabet=_value_alphabet, min_size=1)

# Literal segments: non-empty runs of separator characters.
literals = st.text(alphabet=_SEPARATORS, min_size=1)

# Placeholder/attribute names: valid identifiers matching the keys regex
# ``[a-zA-Z_][a-zA-Z0-9_]*`` (ASCII only -- the regex does not match Unicode).
_ascii_letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_name_first = st.sampled_from(_ascii_letters)
_name_rest = st.text(alphabet=_ascii_letters + "0123456789", max_size=6)
names = st.builds(lambda a, b: a + b, _name_first, _name_rest)


@st.composite
def template_and_attrs(draw: st.DrawFn) -> tuple[str, dict[str, str]]:
    """Build a template with unambiguous separators plus matching attrs.

    Returns ``(template, attrs)`` where ``render`` then ``parse`` is guaranteed
    to recover ``attrs`` exactly.
    """
    field_names = draw(st.lists(names, min_size=1, max_size=4, unique=True))
    attrs: dict[str, str] = {}
    # Start with a literal prefix so the first placeholder is anchored, then
    # alternate placeholder/literal so every placeholder is fully delimited.
    template = draw(literals)
    for name in field_names:
        template += "{" + name + "}"
        template += draw(literals)
        attrs[name] = draw(values)
    return template, attrs


@_SETTINGS
@given(template_and_attrs())
def test_template_fields_in_order(case: tuple[str, dict[str, str]]) -> None:
    template, attrs = case
    assert template_fields(template) == list(attrs.keys())


@_SETTINGS
@given(template_and_attrs())
def test_render_parse_symmetry(case: tuple[str, dict[str, str]]) -> None:
    template, attrs = case
    rendered = render(template, attrs)
    assert parse(template, rendered) == attrs


@_SETTINGS
@given(template_and_attrs(), st.data())
def test_render_missing_attribute_raises(
    case: tuple[str, dict[str, str]], data: st.DataObject
) -> None:
    template, attrs = case
    # Drop one referenced attribute -> render must raise.
    victim = data.draw(st.sampled_from(list(attrs.keys())))
    incomplete = {k: v for k, v in attrs.items() if k != victim}
    with pytest.raises(KeyTemplateError):
        render(template, incomplete)


@_SETTINGS
@given(template_and_attrs(), st.data())
def test_render_none_attribute_raises(
    case: tuple[str, dict[str, str]], data: st.DataObject
) -> None:
    template, attrs = case
    victim = data.draw(st.sampled_from(list(attrs.keys())))
    with_none = {**attrs, victim: None}
    with pytest.raises(KeyTemplateError):
        render(template, with_none)
