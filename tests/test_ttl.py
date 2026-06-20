"""Tests for the TTL attribute mechanism (``ttl_attr``)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pydynantic import Entity, key
from pydynantic.attributes import ttl_attr


def _raw_item(models: SimpleNamespace, cls: type[Entity], **key_attrs: object) -> dict:
    """Read the RAW stored DynamoDB item (AttributeValue form) for a key."""
    response = models.table.client.get_item(
        TableName=models.table.name,
        Key=cls.build_key(key_attrs),
    )
    return response.get("Item", {})


def test_ttl_stored_as_number(models: SimpleNamespace) -> None:
    expires_at = datetime(2030, 6, 1, 12, 30, 45, tzinfo=timezone.utc)
    session = models.Session(session_id="s1", user_id="u1", expires_at=expires_at)
    models.Session.put(session)

    raw = _raw_item(models, models.Session, session_id="s1", user_id="u1")
    assert "expires_at" in raw
    # Stored as a Number, not a String.
    assert raw["expires_at"] == {"N": str(int(expires_at.timestamp()))}
    assert "S" not in raw["expires_at"]


def test_ttl_round_trip_to_the_second(models: SimpleNamespace) -> None:
    expires_at = datetime(2030, 6, 1, 12, 30, 45, 123456, tzinfo=timezone.utc)
    models.Session.put(models.Session(session_id="s2", user_id="u1", expires_at=expires_at))

    fetched = models.Session.get(session_id="s2", user_id="u1")
    assert fetched is not None
    assert fetched.expires_at is not None
    # Sub-second precision is dropped (epoch seconds); compare to the second.
    assert int(fetched.expires_at.timestamp()) == int(expires_at.timestamp())


def test_ttl_none_is_omitted(models: SimpleNamespace) -> None:
    models.Session.put(models.Session(session_id="s3", user_id="u1"))

    raw = _raw_item(models, models.Session, session_id="s3", user_id="u1")
    assert "expires_at" not in raw

    fetched = models.Session.get(session_id="s3", user_id="u1")
    assert fetched is not None
    assert fetched.expires_at is None


def test_ttl_int_passthrough(models: SimpleNamespace) -> None:
    table = models.table

    class IntSession(Entity, table=table, name="int_session"):
        session_id: str
        user_id: str
        expires_at: int = ttl_attr()

        class Meta:
            primary = key(pk="USER#{user_id}", sk="INTSESSION#{session_id}")

    epoch = 1900000000
    IntSession.put(IntSession(session_id="x1", user_id="u1", expires_at=epoch))

    raw = _raw_item(models, IntSession, session_id="x1", user_id="u1")
    assert raw["expires_at"] == {"N": str(epoch)}

    fetched = IntSession.get(session_id="x1", user_id="u1")
    assert fetched is not None
    assert fetched.expires_at == epoch


def test_more_than_one_ttl_field_raises(models: SimpleNamespace) -> None:
    table = models.table

    with pytest.raises(TypeError, match="more than one TTL field"):

        class BadSession(Entity, table=table, name="bad_session"):
            session_id: str
            user_id: str
            expires_at: datetime | None = ttl_attr()
            other_ttl: datetime | None = ttl_attr()

            class Meta:
                primary = key(pk="USER#{user_id}", sk="BAD#{session_id}")
