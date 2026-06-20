"""Tests for Python <-> DynamoDB marshalling of every supported type."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
from pydantic import BaseModel

from pydynantic.errors import PydynanticError
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


# --- Empty strings are intentionally retained (DynamoDB allows them) ---------


def test_empty_string_serializes_to_S() -> None:
    assert serialize("") == {"S": ""}


def test_empty_string_value_roundtrips() -> None:
    assert deserialize(serialize("")) == ""


def test_empty_string_in_list_roundtrips() -> None:
    av = serialize(["", "x"])
    assert av == {"L": [{"S": ""}, {"S": "x"}]}
    assert deserialize(av) == ["", "x"]


def test_empty_string_as_map_value_roundtrips() -> None:
    av = serialize({"k": ""})
    assert av == {"M": {"k": {"S": ""}}}
    assert deserialize(av) == {"k": ""}


def test_empty_string_as_set_element_roundtrips() -> None:
    av = serialize({"", "x"})
    assert set(av["SS"]) == {"", "x"}
    assert deserialize(av) == {"", "x"}


def test_serialize_item_retains_empty_string() -> None:
    item = serialize_item({"a": "", "b": None})
    assert item == {"a": {"S": ""}}


# --- Typed sets: mixed element types are rejected early ----------------------


def test_number_set_mixed_int_and_decimal_is_valid_NS() -> None:
    result = serialize({1, Decimal(2)})
    assert set(result["NS"]) == {"1", "2"}


def test_binary_set_is_valid_BS() -> None:
    result = serialize({b"a", b"b"})
    assert set(result["BS"]) == {b"a", b"b"}


def test_mixed_type_set_raises_pydynantic_error() -> None:
    with pytest.raises(PydynanticError) as excinfo:
        serialize({"a", 1})
    message = str(excinfo.value)
    assert "str" in message
    assert "int" in message


def test_empty_set_still_omitted_by_serialize_item() -> None:
    item = serialize_item({"a": set(), "b": 1})
    assert item == {"b": {"N": "1"}}


# --- Number precision / range validation -------------------------------------


def test_float_out_of_range_raises_pydynantic_error() -> None:
    with pytest.raises(PydynanticError):
        serialize(1e200)


def test_decimal_out_of_range_raises_pydynantic_error() -> None:
    with pytest.raises(PydynanticError):
        serialize(Decimal("1e200"))


def test_decimal_excessive_significant_digits_raises() -> None:
    with pytest.raises(PydynanticError):
        serialize(Decimal("1" * 39))


def test_decimal_trailing_zero_preserved_regression() -> None:
    assert serialize(Decimal("1.50")) == {"N": "1.50"}


def test_normal_numbers_unaffected() -> None:
    assert serialize(5) == {"N": "5"}
    assert serialize(-42) == {"N": "-42"}
    assert serialize(1.5) == {"N": "1.5"}
    assert serialize(Decimal("3.14159")) == {"N": "3.14159"}
    assert serialize(10**30) == {"N": "1" + "0" * 30}


def test_set_family_fallback_names_unknown_type() -> None:
    """A set element of an unrecognised family makes the error name its type."""
    with pytest.raises(PydynanticError) as excinfo:
        # None is prepared as-is and falls into _set_family's fallback branch,
        # making the set heterogeneous against the string element.
        serialize({None, "a"})
    assert "NoneType" in str(excinfo.value)


def test_prepare_empty_set_returns_empty_set() -> None:
    from pydynantic.marshalling import _prepare

    assert _prepare(set()) == set()


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
