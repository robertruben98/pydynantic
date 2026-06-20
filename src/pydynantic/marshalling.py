"""Bidirectional marshalling between Python values and DynamoDB AttributeValues.

This module wraps boto3's :class:`TypeSerializer`/:class:`TypeDeserializer` and
extends them with the richer set of Python types pydynantic supports
(``datetime``, ``date``, ``UUID``, ``Enum``, ``float`` and Pydantic models).

The serializer never emits DynamoDB ``float`` (which is unsupported); every
number is normalised to :class:`~decimal.Decimal` to avoid floating point drift.
"""

from __future__ import annotations

import decimal
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import Enum
from typing import Any, cast
from uuid import UUID

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from pydantic import BaseModel

from .errors import PydynanticError

#: A single DynamoDB AttributeValue, e.g. ``{"S": "hello"}``.
AttributeValue = dict[str, Any]
#: A full DynamoDB item, mapping attribute name -> AttributeValue.
Item = dict[str, AttributeValue]

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()

#: DynamoDB number constraints: up to 38 significant digits, with an exponent
#: range roughly Emin=-130..Emax=125. We validate (but do not reformat) every
#: number against this context so invalid values fail with a friendly error
#: before boto3/DynamoDB ever sees them.
_NUMBER_CONTEXT = decimal.Context(prec=38, Emax=125, Emin=-130)


def _check_number(d: Decimal) -> Decimal:
    """Validate ``d`` against DynamoDB's number precision/range.

    The value is **not** reformatted -- it is run through a strict
    :class:`decimal.Context` purely to detect out-of-range magnitudes or
    excessive significant digits, which are re-raised as
    :class:`~pydynantic.errors.PydynanticError`. The original ``Decimal`` is
    returned unchanged so e.g. ``Decimal("1.50")`` keeps its trailing zero.
    """
    try:
        with localcontext(_NUMBER_CONTEXT) as ctx:
            ctx.traps[decimal.InvalidOperation] = True
            ctx.traps[decimal.Overflow] = True
            # Tiny magnitudes (exponent below DynamoDB's Emin) underflow; trap
            # them here so they surface as a friendly PydynanticError instead of
            # a raw ``decimal.Underflow`` from boto3's own DynamoDB context.
            ctx.traps[decimal.Underflow] = True
            ctx.traps[decimal.Subnormal] = True
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            # ``+d`` applies the context, raising if precision/range is exceeded.
            _ = +d
    except (
        decimal.InvalidOperation,
        decimal.Overflow,
        decimal.Underflow,
        decimal.Subnormal,
        decimal.Inexact,
        decimal.Rounded,
    ) as exc:
        raise PydynanticError(f"number exceeds DynamoDB precision/range: {d!r}") from exc
    return d


def _set_family(value: Any) -> str:
    """Classify a prepared set element into a DynamoDB set family.

    DynamoDB sets are homogeneous: ``SS`` (strings), ``NS`` (numbers) or ``BS``
    (binary). ``bool`` is treated as a number, consistent with how it is stored.
    """
    if isinstance(value, str):
        return "string"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if isinstance(value, (bool, int, Decimal)):
        return "number"
    return type(value).__name__


def _prepare(value: Any) -> Any:
    """Coerce an arbitrary Python value into something ``TypeSerializer`` accepts."""
    # ``bool`` must be checked before ``int`` (bool is a subclass of int).
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _prepare(value.value)
    if isinstance(value, float):
        # Route through ``str`` so we get the shortest faithful decimal.
        return _check_number(Decimal(str(value)))
    if isinstance(value, (int, Decimal)):
        # Validate against DynamoDB's range without reformatting: pass the
        # original ``value`` through so ``Decimal("1.50")`` keeps its trailing
        # zero and ints serialize exactly as before.
        _check_number(Decimal(value))
        return value
    if isinstance(value, (str, bytes, bytearray)):
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
        if prepared:
            families = {_set_family(item) for item in prepared}
            if len(families) > 1:
                offending = ", ".join(sorted(type(item).__name__ for item in prepared))
                raise PydynanticError(
                    "DynamoDB sets must be homogeneous (all strings, all "
                    f"numbers, or all binary); got mixed types: {offending}"
                )
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

    Only ``None`` values and empty sets are skipped, because DynamoDB cannot
    store them as part of an item (use ``REMOVE`` to delete attributes instead).

    Empty strings (``""``) are intentionally **retained**: DynamoDB has allowed
    empty string attribute values since 2020, so ``""`` is a valid, storable
    value and round-trips faithfully -- it is not treated like ``None``.
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
