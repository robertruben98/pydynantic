"""Tests for key template composition and parsing."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

import pytest

from pydynantic import KeyDefinition, Table, key
from pydynantic.errors import KeyTemplateError
from pydynantic.keys import parse, render, template_fields


class _Color(str, Enum):
    RED = "red"


def test_template_fields_order() -> None:
    assert template_fields("ORG#{org_id}#STATUS#{status}") == ["org_id", "status"]
    assert template_fields("STATIC") == []


def test_render_single_and_multiple_placeholders() -> None:
    assert render("USER#{user_id}", {"user_id": "u1"}) == "USER#u1"
    rendered = render("ORG#{org}#STATUS#{status}", {"org": "acme", "status": "active"})
    assert rendered == "ORG#acme#STATUS#active"


def test_render_with_literal_prefix_and_suffix() -> None:
    assert render("PRE#{x}#POST", {"x": "v"}) == "PRE#v#POST"


def test_render_missing_attribute_raises() -> None:
    with pytest.raises(KeyTemplateError, match="org_id"):
        render("ORG#{org_id}", {})


def test_render_none_attribute_raises() -> None:
    with pytest.raises(KeyTemplateError):
        render("ORG#{org_id}", {"org_id": None})


def test_parse_is_reverse_of_render() -> None:
    template = "ORG#{org_id}#STATUS#{status}"
    composed = render(template, {"org_id": "acme", "status": "active"})
    assert parse(template, composed) == {"org_id": "acme", "status": "active"}


def test_parse_single_placeholder() -> None:
    assert parse("USER#{user_id}", "USER#u1") == {"user_id": "u1"}


def test_parse_mismatch_raises() -> None:
    with pytest.raises(KeyTemplateError):
        parse("USER#{user_id}", "ORDER#1")


def test_key_factory_returns_definition() -> None:
    definition = key(pk="ORG#{org_id}", sk="USER#{user_id}", index="GSI1")
    assert isinstance(definition, KeyDefinition)
    assert definition.index == "GSI1"
    assert definition.referenced_fields == {"org_id", "user_id"}


def test_key_attributes_skips_when_fields_missing(models: object) -> None:
    user_key = models.User.__keys__["by_email"]  # type: ignore[attr-defined]
    # Missing ``email`` -> the GSI is not projected for this partial attr set.
    assert user_key.key_attributes({"user_id": "u1"}) == {}


def test_build_key_attributes_for_index(models: object) -> None:
    user_key = models.User.__keys__["by_email"]  # type: ignore[attr-defined]
    attrs = {"email": "a@x.com", "user_id": "u1"}
    assert user_key.key_attributes(attrs) == {"GSI1PK": "EMAIL#a@x.com", "GSI1SK": "USER#u1"}


def test_render_bool_lowercased() -> None:
    assert render("FLAG#{active}", {"active": True}) == "FLAG#true"
    assert render("FLAG#{active}", {"active": False}) == "FLAG#false"


def test_render_date_and_datetime_isoformat() -> None:
    d = date(2024, 1, 2)
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert render("D#{d}", {"d": d}) == "D#2024-01-02"
    assert render("T#{t}", {"t": dt}) == f"T#{dt.isoformat()}"


def test_render_enum_uses_value() -> None:
    assert render("C#{c}", {"c": _Color.RED}) == "C#red"


def test_key_with_sk_on_keyless_index_raises() -> None:
    """A key declaring an sk bound to an index with no sort key is rejected."""
    table = Table("t", indexes={"GSI_NOSK": {"pk": "GSI_NOSK_PK"}}, client=object())
    definition = key(index="GSI_NOSK", pk="P#{a}", sk="S#{b}")
    with pytest.raises(KeyTemplateError, match="no sort key"):
        definition.bind("bad", table)


def test_sk_less_key_build_sk_and_attributes() -> None:
    """A key without a sort key: build_sk is None and the sk attr is omitted."""
    table = Table("t", indexes={"GSI_NOSK": {"pk": "GSI_NOSK_PK"}}, client=object())
    definition = key(index="GSI_NOSK", pk="P#{a}")
    definition.bind("nosk", table)
    assert definition.build_sk({"a": "1"}) is None
    assert definition.key_attributes({"a": "1"}) == {"GSI_NOSK_PK": "P#1"}
