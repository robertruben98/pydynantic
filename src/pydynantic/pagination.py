"""Opaque, serializable pagination cursors and page results."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .errors import PydynanticError
from .marshalling import AttributeValue

T = TypeVar("T")

# DynamoDB ``LastEvaluatedKey`` values are AttributeValues; ``B`` (bytes) is the
# only non-JSON-serializable form, so we base64-wrap it under a private tag.
_BYTES_TAG = "__b64__"


def encode_cursor(last_evaluated_key: dict[str, AttributeValue] | None) -> str | None:
    """Encode a DynamoDB ``LastEvaluatedKey`` into an opaque cursor string."""
    if not last_evaluated_key:
        return None

    def _clean(value: AttributeValue) -> AttributeValue:
        out: AttributeValue = {}
        for type_code, raw in value.items():
            if type_code == "B" and isinstance(raw, (bytes, bytearray)):
                out[type_code] = {_BYTES_TAG: base64.b64encode(raw).decode("ascii")}
            else:
                out[type_code] = raw
        return out

    payload = {name: _clean(av) for name, av in last_evaluated_key.items()}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str | None) -> dict[str, AttributeValue] | None:
    """Decode an opaque cursor back into a DynamoDB ``ExclusiveStartKey``."""
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise PydynanticError(f"Invalid pagination cursor: {exc}") from exc

    def _restore(value: AttributeValue) -> AttributeValue:
        out: AttributeValue = {}
        for type_code, raw_value in value.items():
            if (
                type_code == "B"
                and isinstance(raw_value, dict)
                and _BYTES_TAG in raw_value
            ):
                out[type_code] = base64.b64decode(raw_value[_BYTES_TAG])
            else:
                out[type_code] = raw_value
        return out

    return {name: _restore(av) for name, av in payload.items()}


@dataclass
class Page(Generic[T]):
    """A single page of query results plus a cursor for the next page."""

    items: list[T] = field(default_factory=list)
    cursor: str | None = None

    @property
    def has_more(self) -> bool:
        """Whether another page is available (a cursor was returned)."""
        return self.cursor is not None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
