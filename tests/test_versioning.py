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


def test_update_increments_version(models: object) -> None:
    Order = models.Order  # type: ignore[attr-defined]
    Order.put(Order(order_id="o1", customer_id="c1", total=10.0))
    updated = Order.update(customer_id="c1", order_id="o1", set={"total": 20.0})
    assert updated is not None
    assert updated.version == 2  # 1 (from put) + 1 (from update)
    assert updated.total == 20.0
