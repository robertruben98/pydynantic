"""Tests for key template composition and parsing."""

from __future__ import annotations

import pytest

from pydynantic import KeyDefinition, key
from pydynantic.errors import KeyTemplateError
from pydynantic.keys import parse, render, template_fields


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
