"""Bidirectional marshalling between Python values and DynamoDB AttributeValues.

This module wraps boto3's :class:`TypeSerializer`/:class:`TypeDeserializer` and
extends them with the richer set of Python types pydynantic supports
(``datetime``, ``date``, ``UUID``, ``Enum``, ``float`` and Pydantic models).

The serializer never emits DynamoDB ``float`` (which is unsupported); every
number is normalised to :class:`~decimal.Decimal` to avoid floating point drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from pydantic import BaseModel

#: A single DynamoDB AttributeValue, e.g. ``{"S": "hello"}``.
AttributeValue = dict[str, Any]
#: A full DynamoDB item, mapping attribute name -> AttributeValue.
Item = dict[str, AttributeValue]

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _prepare(value: Any) -> Any:
    """Coerce an arbitrary Python value into something ``TypeSerializer`` accepts."""
    # ``bool`` must be checked before ``int`` (bool is a subclass of int).
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _prepare(value.value)
    if isinstance(value, float):
        # Route through ``str`` so we get the shortest faithful decimal.
        return Decimal(str(value))
    if isinstance(value, (int, Decimal, str, bytes, bytearray)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return {key: _prepare(val) for key, val in value.model_dump(mode="python").items()}
    if isinstance(value, Mapping):
        return {str(key): _prepare(val) for key, val in value.items()}
    if isinstance(value, (set, frozenset)):
        prepared = {_prepare(item) for item in value}
        return prepared
    if isinstance(value, (list, tuple)):
        return [_prepare(item) for item in value]
    raise TypeError(f"Cannot marshal value of type {type(value)!r} to DynamoDB")


def serialize(value: Any) -> AttributeValue:
    """Serialize a single Python value to a DynamoDB AttributeValue."""
    return cast(AttributeValue, _serializer.serialize(_prepare(value)))


def deserialize(attribute_value: AttributeValue) -> Any:
    """Deserialize a single DynamoDB AttributeValue to a Python value."""
    return _deserializer.deserialize(cast(Any, attribute_value))


def serialize_item(data: Mapping[str, Any]) -> Item:
    """Serialize a mapping of attribute name -> Python value to a DynamoDB item.

    ``None`` values and empty sets are skipped because DynamoDB cannot store
    them as part of an item (use ``REMOVE`` to delete attributes instead).
    """
    item: Item = {}
    for name, value in data.items():
        if value is None:
            continue
        if isinstance(value, (set, frozenset)) and not value:
            continue
        item[name] = serialize(value)
    return item


def deserialize_item(item: Mapping[str, AttributeValue]) -> dict[str, Any]:
    """Deserialize a DynamoDB item into a plain Python dict."""
    return {name: deserialize(value) for name, value in item.items()}
