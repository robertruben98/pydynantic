"""Tests for transactional writes and rollback semantics."""

from __future__ import annotations

import pytest

from pydynantic import F, attr_not_exists, transaction
from pydynantic.errors import PydynanticError, TransactionCanceledError


def test_transaction_commits_all(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    with transaction(models.table) as tx:  # type: ignore[attr-defined]
        tx.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
        tx.put(Membership(org_id="acme", user_id="u1", role="admin"))

    assert User.get(org_id="acme", user_id="u1") is not None
    member = Membership.get(org_id="acme", user_id="u1")
    assert member is not None and member.role == "admin"


def test_transaction_update_and_delete(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana", login_count=1))
    User.put(User(user_id="u2", org_id="acme", email="b@x.com", name="Bob"))

    with transaction(models.table) as tx:  # type: ignore[attr-defined]
        tx.update(User, key=("acme", "u1"), set={"name": "Ana B."}, add={"login_count": 5})
        tx.delete(User, key={"org_id": "acme", "user_id": "u2"})

    u1 = User.get(org_id="acme", user_id="u1")
    assert u1 is not None and u1.name == "Ana B." and u1.login_count == 6
    assert User.get(org_id="acme", user_id="u2") is None


def test_transaction_rolls_back_on_failed_condition(models: object) -> None:
    """A failed condition cancels the whole transaction; no partial effects."""
    User = models.User  # type: ignore[attr-defined]
    User.put(User(user_id="existing", org_id="acme", email="e@x.com", name="E"))

    with pytest.raises(TransactionCanceledError):
        with transaction(models.table) as tx:  # type: ignore[attr-defined]
            tx.put(User(user_id="new", org_id="acme", email="n@x.com", name="New"))
            # This condition fails because the item already exists.
            tx.put(
                User(user_id="existing", org_id="acme", email="e@x.com", name="Dup"),
                condition=attr_not_exists("PK"),
            )

    # The first put must NOT have been applied.
    assert User.get(org_id="acme", user_id="new") is None


def test_transaction_condition_check(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana", login_count=10))

    with transaction(models.table) as tx:  # type: ignore[attr-defined]
        tx.condition_check(User, key=("acme", "u1"), condition=F("login_count") >= 5)
        tx.put(Membership(org_id="acme", user_id="u1", role="vip"))

    assert Membership.get(org_id="acme", user_id="u1") is not None


def test_transaction_failed_condition_check_rolls_back(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana", login_count=1))

    with pytest.raises(TransactionCanceledError):
        with transaction(models.table) as tx:  # type: ignore[attr-defined]
            tx.condition_check(User, key=("acme", "u1"), condition=F("login_count") >= 5)
            tx.put(Membership(org_id="acme", user_id="u1", role="vip"))

    assert Membership.get(org_id="acme", user_id="u1") is None


def test_body_exception_prevents_commit(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        with transaction(models.table) as tx:  # type: ignore[attr-defined]
            tx.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
            raise RuntimeError("boom")
    assert User.get(org_id="acme", user_id="u1") is None


def test_update_requires_clause(models: object) -> None:
    with pytest.raises(PydynanticError):
        with transaction(models.table) as tx:  # type: ignore[attr-defined]
            tx.update(models.User, key=("acme", "u1"))  # type: ignore[attr-defined]


def test_transaction_update_remove_and_delete_clauses(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(
        User(user_id="u1", org_id="acme", email="a@x.com", name="Ana", login_count=3,
             tags={"a", "b"})
    )
    with transaction(models.table) as tx:  # type: ignore[attr-defined]
        tx.update(
            User,
            key=("acme", "u1"),
            remove=["login_count"],
            delete={"tags": {"a"}},
            condition=F("name") == "Ana",
        )
    fetched = User.get(org_id="acme", user_id="u1")
    assert fetched is not None
    assert fetched.login_count == 0
    assert fetched.tags == {"b"}


def test_transaction_delete_with_condition_rolls_back(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    with pytest.raises(TransactionCanceledError):
        with transaction(models.table) as tx:  # type: ignore[attr-defined]
            tx.delete(User, key=("acme", "u1"), condition=F("name") == "wrong")
    assert User.get(org_id="acme", user_id="u1") is not None


def test_transaction_capacity_limit(models: object) -> None:
    from pydynantic.transactions import MAX_TRANSACTION_ITEMS, Transaction

    User = models.User  # type: ignore[attr-defined]
    tx = Transaction(models.table)  # type: ignore[attr-defined]
    for i in range(MAX_TRANSACTION_ITEMS):
        tx.put(User(user_id=f"u{i}", org_id="acme", email=f"{i}@x.com", name="N"))
    with pytest.raises(PydynanticError):
        tx.put(User(user_id="overflow", org_id="acme", email="o@x.com", name="N"))
