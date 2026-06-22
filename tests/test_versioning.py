"""Tests for optimistic locking via version attributes."""

from __future__ import annotations

import pytest

from pydynantic.errors import OptimisticLockError


def test_put_increments_version(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    order = Order(order_id="o1", customer_id="c1", total=10.0)
    assert order.version == 0
    stored = Order.put(order)
    assert stored.version == 1

    fetched = Order.get(customer_id="c1", order_id="o1")
    assert fetched is not None and fetched.version == 1


def test_sequential_puts_increment(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))
    fetched = Order.get(customer_id="c1", order_id="o1")
    assert fetched is not None
    Order.put(fetched)  # version 1 -> 2
    again = Order.get(customer_id="c1", order_id="o1")
    assert again is not None and again.version == 2


def test_stale_write_raises_optimistic_lock(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))

    # Two clients read the same version-1 item.
    client_a = Order.get(customer_id="c1", order_id="o1")
    client_b = Order.get(customer_id="c1", order_id="o1")
    assert client_a is not None and client_b is not None

    # Client A writes first, bumping the stored version to 2.
    Order.put(client_a)

    # Client B still thinks the version is 1 -> its conditional put must fail.
    with pytest.raises(OptimisticLockError):
        Order.put(client_b)

    # The failed write must not leave B's in-memory version bumped, so a fresh
    # read + retry can still succeed.
    assert client_b.version == 1


def test_update_increments_version(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))
    updated = Order.update(customer_id="c1", order_id="o1", set={"total": 20.0})
    assert updated is not None
    assert updated.version == 2  # 1 (from put) + 1 (from update)
    assert updated.total == 20.0


def test_update_with_matching_expected_version_succeeds(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))  # version -> 1
    updated = Order.update(customer_id="c1", order_id="o1", set={"total": 20.0}, expected_version=1)
    assert updated is not None
    assert updated.version == 2
    assert updated.total == 20.0


def test_update_with_stale_expected_version_raises(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))  # version -> 1
    # Someone else advances the version to 2.
    Order.update(customer_id="c1", order_id="o1", set={"total": 15.0}, expected_version=1)
    # A caller still believing the version is 1 must fail loudly, not lose the write.
    with pytest.raises(OptimisticLockError):
        Order.update(customer_id="c1", order_id="o1", set={"total": 99.0}, expected_version=1)
    fetched = Order.get(customer_id="c1", order_id="o1")
    assert fetched is not None and fetched.total == 15.0  # stale write did not land


def test_update_expected_version_on_unversioned_entity_raises(models: object) -> None:
    Membership = models.Membership  # type: ignore[attr-defined]
    Membership.put(Membership(org_id="o1", user_id="u1", role="member"))
    with pytest.raises(ValueError):
        Membership.update(org_id="o1", user_id="u1", set={"role": "admin"}, expected_version=1)
