"""Tests for Python <-> DynamoDB marshalling of every supported type."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
from pydantic import BaseModel

from pydynantic.marshalling import deserialize, serialize, serialize_item


class Color(Enum):
    RED = "red"
    GREEN = "green"


def test_serialize_str() -> None:
    assert serialize("hi") == {"S": "hi"}


def test_serialize_bool_before_int() -> None:
    assert serialize(True) == {"BOOL": True}
    assert serialize(False) == {"BOOL": False}


def test_serialize_int_and_decimal() -> None:
    assert serialize(5) == {"N": "5"}
    assert serialize(Decimal("1.50")) == {"N": "1.50"}


def test_serialize_float_uses_decimal() -> None:
    assert serialize(1.5) == {"N": "1.5"}


def test_serialize_none() -> None:
    assert serialize(None) == {"NULL": True}


def test_serialize_bytes() -> None:
    assert serialize(b"abc") == {"B": b"abc"}


def test_serialize_datetime_and_date() -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert serialize(dt) == {"S": dt.isoformat()}
    assert serialize(date(2024, 1, 2)) == {"S": "2024-01-02"}


def test_serialize_uuid() -> None:
    u = UUID("12345678-1234-5678-1234-567812345678")
    assert serialize(u) == {"S": str(u)}


def test_serialize_enum() -> None:
    assert serialize(Color.RED) == {"S": "red"}


def test_serialize_list_and_dict() -> None:
    assert serialize([1, "a"]) == {"L": [{"N": "1"}, {"S": "a"}]}
    assert serialize({"k": 1}) == {"M": {"k": {"N": "1"}}}


def test_serialize_string_set() -> None:
    result = serialize({"a", "b"})
    assert set(result["SS"]) == {"a", "b"}


def test_serialize_number_set() -> None:
    result = serialize({1, 2})
    assert set(result["NS"]) == {"1", "2"}


def test_serialize_nested_pydantic_model() -> None:
    class Address(BaseModel):
        city: str
        zip: int

    assert serialize(Address(city="NYC", zip=10001)) == {
        "M": {"city": {"S": "NYC"}, "zip": {"N": "10001"}}
    }


def test_serialize_unsupported_type_raises() -> None:
    with pytest.raises(TypeError):
        serialize(object())


def test_deserialize_roundtrip() -> None:
    assert deserialize(serialize("hello")) == "hello"
    assert deserialize(serialize(42)) == Decimal("42")


def test_serialize_item_skips_none_and_empty_sets() -> None:
    item = serialize_item({"a": 1, "b": None, "c": set(), "d": "x"})
    assert item == {"a": {"N": "1"}, "d": {"S": "x"}}


def test_full_entity_type_roundtrip(models: object) -> None:
    """Every supported type survives a put/get cycle through DynamoDB."""
    User = models.User  # type: ignore[attr-defined]
    created = datetime(2023, 6, 1, 12, 0, tzinfo=timezone.utc)
    User.put(
        User(
            user_id="t1",
            org_id="acme",
            email="t@x.com",
            name="Type Test",
            login_count=7,
            tags={"x", "y"},
            created_at=created,
        )
    )
    fetched = User.get(org_id="acme", user_id="t1")
    assert fetched is not None
    assert fetched.login_count == 7
    assert fetched.tags == {"x", "y"}
    assert fetched.created_at == created
    assert fetched.status is models.Status.ACTIVE  # type: ignore[attr-defined]
