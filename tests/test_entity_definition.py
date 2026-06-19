"""Tests for entity/table definition-time validation."""

from __future__ import annotations

import pytest

from pydynantic import Entity, Index, Table, key
from pydynantic.errors import KeyTemplateError


def _table() -> Table:
    return Table(
        name="t",
        indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
        client=object(),
    )


def test_index_dataclass() -> None:
    assert Index(pk="P").sk is None
    assert Index(pk="P", sk="S").sk == "S"


def test_table_entity_registry() -> None:
    table = _table()

    class Thing(Entity, table=table, name="thing"):
        id: str

        class Meta:
            primary = key(pk="THING#{id}")

    assert table.entity_for("thing") is Thing
    assert table.entity_for("missing") is None


def test_missing_name_and_table_is_base_like() -> None:
    table = _table()
    with pytest.raises(TypeError):

        class Bad(Entity, table=table):  # missing name=
            id: str

            class Meta:
                primary = key(pk="X#{id}")


def test_no_primary_key_raises() -> None:
    table = _table()
    with pytest.raises(KeyTemplateError):

        class NoPrimary(Entity, table=table, name="np"):
            id: str

            class Meta:
                by_id = key(index="GSI1", pk="X#{id}")


def test_undeclared_attribute_in_template_raises() -> None:
    table = _table()
    with pytest.raises(KeyTemplateError):

        class BadTemplate(Entity, table=table, name="bt"):
            id: str

            class Meta:
                primary = key(pk="X#{nonexistent}")


def test_unknown_index_raises() -> None:
    table = _table()
    with pytest.raises(KeyTemplateError):

        class BadIndex(Entity, table=table, name="bi"):
            id: str

            class Meta:
                primary = key(pk="X#{id}")
                other = key(index="NOPE", pk="Y#{id}")


def test_multiple_primary_keys_raises() -> None:
    table = _table()
    with pytest.raises(KeyTemplateError):

        class TwoPrimary(Entity, table=table, name="tp"):
            id: str

            class Meta:
                primary = key(pk="X#{id}")
                primary2 = key(pk="Y#{id}")


def test_parse_helper_on_definition(models: object) -> None:
    # Parse a composed primary key back into its components.
    from pydynantic.keys import parse

    primary = models.User.__primary_key__  # type: ignore[attr-defined]
    assert parse(primary.sk_template, "USER#u1") == {"user_id": "u1"}
