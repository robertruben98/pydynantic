"""Opaque, serializable pagination cursors and page results.

A cursor is an **opaque** token: a base64url string **without** ``=`` padding,
making it safe to embed directly in URLs, query strings and JSON bodies. Its
payload is *versioned* (``{"v": <int>, "k": <table-key>}``) and JSON-encoded.

Callers must treat cursors as black boxes: pass back verbatim whatever
``Page.cursor`` / :func:`encode_cursor` produced. Never hand-build, mutate or
parse a cursor yourself -- its internal shape is private and may change between
versions. :func:`decode_cursor` validates structure and version and raises
:class:`~pydynantic.errors.PydynanticError` on anything it does not recognise,
so a stale or corrupted cursor fails loudly rather than silently misbehaving.

Note: cursors are **not** HMAC-signed. They encode only a DynamoDB table key
that the caller could already query directly, so there is no secret to protect;
versioning plus validation buys loud, well-defined failure without the burden
of key management.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from .errors import PydynanticError
from .marshalling import AttributeValue

T = TypeVar("T")

# DynamoDB ``LastEvaluatedKey`` values are AttributeValues; ``B`` (bytes) is the
# only non-JSON-serializable form, so we base64-wrap it under a private tag.
_BYTES_TAG = "__b64__"

# Bumped whenever the cursor payload shape changes; cursors carrying any other
# version are rejected by :func:`decode_cursor`.
_CURSOR_VERSION = 1


def encode_cursor(last_evaluated_key: dict[str, AttributeValue] | None) -> str | None:
    """Encode a DynamoDB ``LastEvaluatedKey`` into an opaque cursor string.

    Returns a versioned, base64url-encoded token **without** ``=`` padding
    (HTTP/JSON-safe). ``None`` or an empty key yields ``None``. The result is
    opaque: pass it back verbatim to resume pagination; do not parse or build
    one by hand.
    """
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

    key = {name: _clean(av) for name, av in last_evaluated_key.items()}
    payload = {"v": _CURSOR_VERSION, "k": key}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    # Strip ``=`` padding so cursors are clean for URLs/JSON; re-added on decode.
    return encoded.rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, AttributeValue] | None:
    """Decode an opaque cursor back into a DynamoDB ``ExclusiveStartKey``.

    ``None`` decodes to ``None``. The cursor must be exactly the opaque,
    versioned token produced by :func:`encode_cursor` -- it is never
    hand-built. Any malformed, non-JSON, structurally-wrong or
    unsupported-version cursor raises :class:`~pydynantic.errors.PydynanticError`
    rather than leaking a raw decoding exception.
    """
    if cursor is None:
        return None

    # Re-add the ``=`` padding stripped during encoding before decoding.
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise PydynanticError(f"Invalid pagination cursor (malformed base64): {exc}") from exc

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise PydynanticError(f"Invalid pagination cursor (not valid JSON): {exc}") from exc

    if not isinstance(payload, dict):
        raise PydynanticError("Invalid pagination cursor: payload is not a JSON object.")

    version = payload.get("v")
    if version != _CURSOR_VERSION:
        raise PydynanticError(
            f"Invalid pagination cursor: unsupported version {version!r} "
            f"(expected {_CURSOR_VERSION})."
        )

    key = payload.get("k")
    if not isinstance(key, dict):
        raise PydynanticError("Invalid pagination cursor: missing or malformed key payload.")

    def _restore(name: str, value: Any) -> AttributeValue:
        if not isinstance(value, dict):
            raise PydynanticError(
                f"Invalid pagination cursor: key entry {name!r} is not an AttributeValue mapping."
            )
        out: AttributeValue = {}
        for type_code, raw_value in value.items():
            if type_code == "B" and isinstance(raw_value, dict) and _BYTES_TAG in raw_value:
                out[type_code] = base64.b64decode(raw_value[_BYTES_TAG])
            else:
                out[type_code] = raw_value
        return out

    return {name: _restore(name, av) for name, av in key.items()}


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
