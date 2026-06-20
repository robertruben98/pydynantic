"""Tests for batch get/write, including chunking and unprocessed retries."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from pydynantic import batch as batch_module
from pydynantic.errors import PydynanticError


def seed(models: object, n: int) -> None:
    User = models.User  # type: ignore[attr-defined]
    for i in range(1, n + 1):
        User.put(User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name=f"N{i}"))


def test_batch_write_and_get(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    users = [
        User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name=f"N{i}") for i in range(5)
    ]
    User.batch_write(puts=users)

    fetched = User.batch_get([("acme", f"u{i}") for i in range(5)])
    assert {u.user_id for u in fetched} == {f"u{i}" for i in range(5)}


def test_batch_write_chunks_over_25(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    users = [User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name="N") for i in range(60)]
    User.batch_write(puts=users)
    assert len(User.query.primary(org_id="acme").all()) == 60


def test_batch_get_chunks_over_100(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    users = [
        User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name="N") for i in range(150)
    ]
    User.batch_write(puts=users)
    fetched = User.batch_get([("acme", f"u{i}") for i in range(150)])
    assert len(fetched) == 150


def test_batch_get_projection(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    for i in range(3):
        User.put(
            User(
                user_id=f"u{i}",
                org_id="acme",
                email=f"u{i}@x.com",
                name=f"N{i}",
                login_count=7,
            )
        )
    fetched = User.batch_get(
        [("acme", f"u{i}") for i in range(3)],
        attributes=["user_id", "org_id", "email", "name"],
    )
    assert {u.user_id for u in fetched} == {"u0", "u1", "u2"}
    assert all(isinstance(u, User) for u in fetched)
    # login_count was projected away, so it falls back to its model default.
    assert all(u.login_count == 0 for u in fetched)


def test_batch_get_projection_over_100(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    users = [
        User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name="N", login_count=5)
        for i in range(150)
    ]
    User.batch_write(puts=users)
    fetched = User.batch_get(
        [("acme", f"u{i}") for i in range(150)],
        attributes=["user_id", "org_id", "email", "name"],
    )
    assert len(fetched) == 150
    assert all(u.login_count == 0 for u in fetched)


def test_batch_write_deletes(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    seed(models, 3)
    User.batch_write(deletes=[("acme", "u1"), ("acme", "u2")])
    remaining = User.query.primary(org_id="acme").all()
    assert {u.user_id for u in remaining} == {"u3"}


def test_batch_get_accepts_dict_keys(models: object) -> None:
    seed(models, 2)
    fetched = models.User.batch_get([{"org_id": "acme", "user_id": "u1"}])  # type: ignore[attr-defined]
    assert len(fetched) == 1


def test_batch_get_dedupes_duplicate_keys(models: object) -> None:
    # DynamoDB rejects duplicate keys in one BatchGetItem; we must dedupe first.
    seed(models, 1)
    fetched = models.User.batch_get(  # type: ignore[attr-defined]
        [("acme", "u1"), ("acme", "u1"), {"org_id": "acme", "user_id": "u1"}]
    )
    assert len(fetched) == 1


def test_batch_get_retries_unprocessed_keys(models: object, monkeypatch: Any) -> None:
    """Simulate UnprocessedKeys to exercise the retry loop."""
    User = models.User  # type: ignore[attr-defined]
    seed(models, 2)
    client = models.table.client  # type: ignore[attr-defined]
    real_batch_get = client.batch_get_item
    calls = {"n": 0}

    def flaky(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # Return nothing but report all requested keys as unprocessed.
            return {"Responses": {}, "UnprocessedKeys": kwargs["RequestItems"]}
        return real_batch_get(**kwargs)

    monkeypatch.setattr(client, "batch_get_item", flaky)
    monkeypatch.setattr(batch_module, "_backoff", lambda attempt: None)
    fetched = User.batch_get([("acme", "u1"), ("acme", "u2")])
    assert calls["n"] == 2
    assert len(fetched) == 2


def test_batch_write_retries_unprocessed_items(models: object, monkeypatch: Any) -> None:
    User = models.User  # type: ignore[attr-defined]
    client = models.table.client  # type: ignore[attr-defined]
    real_write = client.batch_write_item
    calls = {"n": 0}

    def flaky(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"UnprocessedItems": kwargs["RequestItems"]}
        return real_write(**kwargs)

    monkeypatch.setattr(client, "batch_write_item", flaky)
    monkeypatch.setattr(batch_module, "_backoff", lambda attempt: None)
    User.batch_write(puts=[User(user_id="u1", org_id="acme", email="a@x.com", name="A")])
    assert calls["n"] == 2
    assert User.get(org_id="acme", user_id="u1") is not None


def test_backoff_is_capped(monkeypatch: Any) -> None:
    """``_backoff`` caps the exponential sleep at 1.0 second."""
    slept: list[float] = []
    monkeypatch.setattr(batch_module.time, "sleep", lambda secs: slept.append(secs))
    batch_module._backoff(1)  # 2**0 * 0.05 = 0.05
    batch_module._backoff(8)  # would be 6.4 -> capped to 1.0
    assert slept[0] == pytest.approx(0.05)
    assert slept[1] == 1.0


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "BatchOp")


def test_batch_get_client_error_maps_to_pydynantic(models: object, monkeypatch: Any) -> None:
    User = models.User  # type: ignore[attr-defined]
    client = models.table.client  # type: ignore[attr-defined]

    def boom(**kwargs: Any) -> Any:
        raise _client_error("ResourceNotFoundException")

    monkeypatch.setattr(client, "batch_get_item", boom)
    with pytest.raises(PydynanticError):
        User.batch_get([("acme", "u1")])


def test_batch_get_retry_exhausted_raises_runtime(models: object, monkeypatch: Any) -> None:
    User = models.User  # type: ignore[attr-defined]
    client = models.table.client  # type: ignore[attr-defined]

    def always_unprocessed(**kwargs: Any) -> Any:
        return {"Responses": {}, "UnprocessedKeys": kwargs["RequestItems"]}

    monkeypatch.setattr(client, "batch_get_item", always_unprocessed)
    monkeypatch.setattr(batch_module, "_backoff", lambda attempt: None)
    with pytest.raises(RuntimeError, match="batch_get gave up"):
        User.batch_get([("acme", "u1")])


def test_batch_write_client_error_maps_to_pydynantic(models: object, monkeypatch: Any) -> None:
    User = models.User  # type: ignore[attr-defined]
    client = models.table.client  # type: ignore[attr-defined]

    def boom(**kwargs: Any) -> Any:
        raise _client_error("ResourceNotFoundException")

    monkeypatch.setattr(client, "batch_write_item", boom)
    with pytest.raises(PydynanticError):
        User.batch_write(puts=[User(user_id="u1", org_id="acme", email="a@x.com", name="A")])


def test_batch_write_retry_exhausted_raises_runtime(models: object, monkeypatch: Any) -> None:
    User = models.User  # type: ignore[attr-defined]
    client = models.table.client  # type: ignore[attr-defined]

    def always_unprocessed(**kwargs: Any) -> Any:
        return {"UnprocessedItems": kwargs["RequestItems"]}

    monkeypatch.setattr(client, "batch_write_item", always_unprocessed)
    monkeypatch.setattr(batch_module, "_backoff", lambda attempt: None)
    with pytest.raises(RuntimeError, match="batch_write gave up"):
        User.batch_write(puts=[User(user_id="u1", org_id="acme", email="a@x.com", name="A")])
