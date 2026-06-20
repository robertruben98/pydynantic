"""Tests for the observability client proxy and ``on_operation`` hook.

Self-contained: defines its own mocked table + entities (does not import
tests/conftest), so it exercises the public API exactly as a user would.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from pydynantic import (
    ConditionCheckFailedError,
    Entity,
    OperationEvent,
    OptimisticLockError,
    Table,
    attr_not_exists,
    key,
    transaction,
    version_attr,
)

TABLE_NAME = "obs-test"


def _create_table(client: object) -> None:
    client.create_table(  # type: ignore[attr-defined]
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


def _build_models(table: Table) -> SimpleNamespace:
    class User(Entity, table=table, name="user"):
        user_id: str
        org_id: str
        email: str
        name: str

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
            by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")

    class Membership(Entity, table=table, name="membership"):
        org_id: str
        user_id: str
        role: str = "member"

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="MEMBER#{user_id}")

    class Order(Entity, table=table, name="order"):
        order_id: str
        customer_id: str
        version: int = version_attr()

        class Meta:
            primary = key(pk="CUSTOMER#{customer_id}", sk="ORDER#{order_id}")

    return SimpleNamespace(table=table, User=User, Membership=Membership, Order=Order)


def _make(
    on_operation: object = None,
) -> tuple[object, SimpleNamespace]:
    """Build a fresh mocked client + bound models, optionally with a hook."""
    client = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(client)
    kwargs: dict[str, object] = {
        "name": TABLE_NAME,
        "indexes": {"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
        "client": client,
    }
    if on_operation is not None:
        kwargs["on_operation"] = on_operation
    table = Table(**kwargs)  # type: ignore[arg-type]
    return client, _build_models(table)


@pytest.fixture(autouse=True)
def _aws() -> Iterator[None]:
    with mock_aws():
        yield


# 1. Default: no hook means table.client is the raw client (identity).
def test_default_no_proxy() -> None:
    client, models = _make()
    assert models.table.client is client


# 2. Hook fires on success for put and get.
def test_hook_fires_on_success() -> None:
    events: list[OperationEvent] = []
    _, models = _make(on_operation=events.append)
    User = models.User

    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    got = User.get(org_id="acme", user_id="u1")
    assert got is not None

    ops = [e.operation for e in events]
    assert "put_item" in ops
    assert "get_item" in ops
    for e in events:
        assert e.table_name == TABLE_NAME
        assert e.success is True
        assert e.exception is None
        assert e.duration_ms >= 0


# 3. ConsumedCapacity carried when present, None when absent.
def test_consumed_capacity_present_and_absent() -> None:
    events: list[OperationEvent] = []
    _, models = _make(on_operation=events.append)
    User = models.User
    table = models.table

    # Absent: moto does not return ConsumedCapacity for a plain put.
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    put_event = next(e for e in events if e.operation == "put_item")
    assert put_event.consumed_capacity is None

    # Present: call get_item directly through the proxy asking for capacity.
    events.clear()
    table.client.get_item(
        TableName=TABLE_NAME,
        Key={"PK": {"S": "ORG#acme"}, "SK": {"S": "USER#u1"}},
        ReturnConsumedCapacity="TOTAL",
    )
    get_event = next(e for e in events if e.operation == "get_item")
    assert get_event.consumed_capacity is not None


# 4. Failure path: conditional put fails -> hook sees the failure AND the
#    mapped error is still raised to the caller.
def test_failure_path_condition_check() -> None:
    events: list[OperationEvent] = []
    _, models = _make(on_operation=events.append)
    User = models.User

    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    events.clear()

    with pytest.raises(ConditionCheckFailedError):
        User.put(
            User(user_id="u1", org_id="acme", email="a@x.com", name="Dup"),
            condition=attr_not_exists("PK"),
        )

    failed = next(e for e in events if e.operation == "put_item")
    assert failed.success is False
    assert failed.exception is not None
    assert failed.consumed_capacity is None


def test_failure_path_optimistic_lock() -> None:
    events: list[OperationEvent] = []
    _, models = _make(on_operation=events.append)
    Order = models.Order

    Order.put(Order(order_id="o1", customer_id="c1"))
    events.clear()

    # A second create with a stale (default 0) version loses the lock race.
    with pytest.raises(OptimisticLockError):
        Order.put(Order(order_id="o1", customer_id="c1"))

    failed = next(e for e in events if e.operation == "put_item")
    assert failed.success is False
    assert failed.exception is not None


# 5. A hook that raises is swallowed; operation result/exception is unchanged.
def test_hook_that_raises_is_swallowed() -> None:
    def boom(_event: OperationEvent) -> None:
        raise RuntimeError("hook blew up")

    _, models = _make(on_operation=boom)
    User = models.User

    # Success path: operation still returns normally despite the hook raising.
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    assert User.get(org_id="acme", user_id="u1") is not None

    # Failure path: the mapped error still propagates (not the hook's error).
    with pytest.raises(ConditionCheckFailedError):
        User.put(
            User(user_id="u1", org_id="acme", email="a@x.com", name="Dup"),
            condition=attr_not_exists("PK"),
        )


# 6. One wrap covers all modules: query / scan / batch / transaction each fire.
def test_single_wrap_covers_all_modules() -> None:
    events: list[OperationEvent] = []
    _, models = _make(on_operation=events.append)
    User = models.User
    Membership = models.Membership

    User.batch_write(
        puts=[
            User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name=f"N{i}")
            for i in range(3)
        ]
    )
    User.batch_get([("acme", "u0"), ("acme", "u1")])
    User.query.primary(org_id="acme").all()
    User.scan().all()
    with transaction(models.table) as tx:
        tx.put(Membership(org_id="acme", user_id="u1", role="admin"))

    ops = {e.operation for e in events}
    assert "query" in ops
    assert "scan" in ops
    assert "batch_write_item" in ops
    assert "batch_get_item" in ops
    assert "transact_write_items" in ops


# 7. Non-operation attribute access passes through to the raw client.
def test_non_operation_passthrough() -> None:
    client, models = _make(on_operation=lambda e: None)
    proxy = models.table.client

    assert proxy is not client  # a proxy when a hook is set
    # describe_table is not an instrumented op -> forwarded unchanged.
    desc = proxy.describe_table(TableName=TABLE_NAME)
    assert desc["Table"]["TableName"] == TABLE_NAME
    # Non-callable attribute also forwards.
    assert proxy.meta is client.meta
