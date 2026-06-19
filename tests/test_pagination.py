"""Tests for opaque cursor pagination."""

from __future__ import annotations

import pytest

from pydynantic.errors import PydynanticError
from pydynantic.pagination import decode_cursor, encode_cursor


def seed(models: object, n: int) -> None:
    User = models.User  # type: ignore[attr-defined]
    for i in range(1, n + 1):
        User.put(User(user_id=f"u{i:02d}", org_id="acme", email=f"u{i}@x.com", name=f"N{i}"))


def test_encode_decode_roundtrip() -> None:
    lek = {"PK": {"S": "ORG#acme"}, "SK": {"S": "USER#u1"}}
    cursor = encode_cursor(lek)
    assert isinstance(cursor, str)
    assert decode_cursor(cursor) == lek


def test_encode_empty_is_none() -> None:
    assert encode_cursor(None) is None
    assert encode_cursor({}) is None
    assert decode_cursor(None) is None


def test_cursor_does_not_leak_raw_structure() -> None:
    cursor = encode_cursor({"PK": {"S": "secret"}})
    assert "PK" not in cursor
    assert "secret" not in cursor


def test_bytes_key_roundtrip() -> None:
    lek = {"PK": {"B": b"\x00\x01\x02"}}
    assert decode_cursor(encode_cursor(lek)) == lek


def test_invalid_cursor_raises() -> None:
    with pytest.raises(PydynanticError):
        decode_cursor("!!!not-base64!!!")


def test_page_walks_all_items(models: object) -> None:
    seed(models, 5)
    collected: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = models.User.query.primary(org_id="acme").limit(2).page(cursor=cursor)  # type: ignore[attr-defined]
        collected.extend(u.user_id for u in page.items)
        pages += 1
        if not page.has_more:
            break
        cursor = page.cursor
    assert collected == ["u01", "u02", "u03", "u04", "u05"]
    assert pages == 3


def test_page_object_helpers(models: object) -> None:
    seed(models, 2)
    page = models.User.query.primary(org_id="acme").page()  # type: ignore[attr-defined]
    assert len(page) == 2
    assert list(page) == page.items
