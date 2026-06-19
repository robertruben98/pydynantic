"""Tests for the F() condition/filter DSL and placeholder management."""

from __future__ import annotations

import pytest

from pydynantic import F, attr_exists, attr_not_exists
from pydynantic.expressions import ExpressionContext


def compile_to(condition: object) -> tuple[str, dict, dict]:
    ctx = ExpressionContext()
    expr = condition.compile(ctx)  # type: ignore[attr-defined]
    return expr, ctx.names, ctx.values


def test_comparison_operators() -> None:
    for op, sym in [("__eq__", "="), ("__ne__", "<>"), ("__lt__", "<"),
                    ("__le__", "<="), ("__gt__", ">"), ("__ge__", ">=")]:
        condition = getattr(F("age"), op)(18)
        expr, names, values = compile_to(condition)
        assert expr == f"#n0 {sym} :v0"
        assert names == {"#n0": "age"}
        assert values == {":v0": {"N": "18"}}


def test_between() -> None:
    expr, names, values = compile_to(F("age").between(10, 20))
    assert expr == "#n0 BETWEEN :v0 AND :v1"
    assert values == {":v0": {"N": "10"}, ":v1": {"N": "20"}}


def test_begins_with_and_contains() -> None:
    expr, _, _ = compile_to(F("sk").begins_with("USER#"))
    assert expr == "begins_with(#n0, :v0)"
    expr, _, _ = compile_to(F("tags").contains("x"))
    assert expr == "contains(#n0, :v0)"


def test_exists_and_not_exists() -> None:
    assert compile_to(F("x").exists())[0] == "attribute_exists(#n0)"
    assert compile_to(F("x").not_exists())[0] == "attribute_not_exists(#n0)"
    assert compile_to(attr_exists("x"))[0] == "attribute_exists(#n0)"
    assert compile_to(attr_not_exists("x"))[0] == "attribute_not_exists(#n0)"


def test_is_in() -> None:
    expr, _, values = compile_to(F("status").is_in(["a", "b"]))
    assert expr == "#n0 IN (:v0, :v1)"
    assert values == {":v0": {"S": "a"}, ":v1": {"S": "b"}}


def test_is_in_empty_raises() -> None:
    with pytest.raises(ValueError):
        F("status").is_in([])


def test_and_or_not_combination() -> None:
    condition = (F("status") == "active") & (F("count") > 0)
    expr, names, values = compile_to(condition)
    assert expr == "(#n0 = :v0 AND #n1 > :v1)"
    assert names == {"#n0": "status", "#n1": "count"}

    expr, _, _ = compile_to((F("a") == 1) | (F("b") == 2))
    assert expr == "(#n0 = :v0 OR #n1 = :v1)"

    expr, _, _ = compile_to(~(F("a") == 1))
    assert expr == "(NOT #n0 = :v0)"


def test_name_reuse_for_same_attribute() -> None:
    condition = (F("status") == "a") | (F("status") == "b")
    expr, names, values = compile_to(condition)
    # Same attribute should reuse the same name placeholder.
    assert names == {"#n0": "status"}
    assert expr == "(#n0 = :v0 OR #n0 = :v1)"


def test_nested_dotted_path() -> None:
    expr, names, _ = compile_to(F("address.city") == "NYC")
    assert expr == "#n0.#n1 = :v0"
    assert names == {"#n0": "address", "#n1": "city"}


def test_compile_condition_helper() -> None:
    from pydynantic.expressions import compile_condition

    expr, ctx = compile_condition(F("a") == 1)
    assert expr == "#n0 = :v0"
    assert ctx.values == {":v0": {"N": "1"}}


def test_attribute_type() -> None:
    expr, _, values = compile_to(F("x").is_type("S"))
    assert expr == "attribute_type(#n0, :v0)"
    assert values == {":v0": {"S": "S"}}
