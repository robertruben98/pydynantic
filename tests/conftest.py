"""Shared pytest fixtures: a mocked DynamoDB table and a set of test entities."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from pydynantic import Collection, Entity, Field, Table, key, version_attr

TABLE_NAME = "app-test"


def _create_table(client: object) -> None:
    client.create_table(  # type: ignore[attr-defined]
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _build_models(table: Table) -> SimpleNamespace:
    class User(Entity, table=table, name="user"):
        user_id: str
        org_id: str
        email: str
        name: str
        status: Status = Status.ACTIVE
        login_count: int = 0
        tags: set[str] = Field(default_factory=set)
        created_at: datetime = Field(
            default_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
            by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
            by_status = key(
                index="GSI2",
                pk="ORG#{org_id}#STATUS#{status}",
                sk="USER#{user_id}",
            )

    class Membership(Entity, table=table, name="membership"):
        org_id: str
        user_id: str
        role: str = "member"

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="MEMBER#{user_id}")

    class Invoice(Entity, table=table, name="invoice"):
        org_id: str
        invoice_id: str
        amount: Decimal = Decimal("0")

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="INVOICE#{invoice_id}")

    class Order(Entity, table=table, name="order"):
        order_id: str
        customer_id: str
        total: float = 0.0
        item_count: int = 0
        version: int = version_attr()

        class Meta:
            primary = key(pk="CUSTOMER#{customer_id}", sk="ORDER#{order_id}")

    class OrgData(Collection):
        members = [User, Membership, Invoice]

    return SimpleNamespace(
        table=table,
        User=User,
        Membership=Membership,
        Invoice=Invoice,
        Order=Order,
        OrgData=OrgData,
        Status=Status,
    )


@pytest.fixture
def models() -> Iterator[SimpleNamespace]:
    """A fresh mocked table plus entity classes bound to it, per test."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        _create_table(client)
        table = Table(
            name=TABLE_NAME,
            indexes={
                "GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"},
                "GSI2": {"pk": "GSI2PK", "sk": "GSI2SK"},
            },
            client=client,
        )
        yield _build_models(table)
