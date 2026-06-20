"""Benchmark fixtures: a moto-mocked table and a representative entity.

Self-contained on purpose -- it does NOT import from ``tests/``. It mirrors the
style of ``tests/conftest.py`` (mock_aws + create_table with PK/SK + a GSI, a
``Table`` plus an ``Entity`` subclass) but keeps a single rich entity tuned for
marshalling/query benchmarks.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from pydynantic import Entity, Field, Table, key

TABLE_NAME = "app-bench"


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
            },
        ],
    )


class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _build_models(table: Table) -> SimpleNamespace:
    class Record(Entity, table=table, name="record"):
        """A representative entity: str/int/Decimal/datetime/list/dict/set."""

        record_id: str
        org_id: str
        title: str
        status: Status = Status.ACTIVE
        login_count: int = 0
        amount: Decimal = Decimal("0")
        created_at: datetime = Field(
            default_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        tags: set[str] = Field(default_factory=set)
        items: list[str] = Field(default_factory=list)
        metadata: dict[str, str] = Field(default_factory=dict)

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="RECORD#{record_id}")
            by_status = key(
                index="GSI1",
                pk="ORG#{org_id}#STATUS#{status}",
                sk="RECORD#{record_id}",
            )

    return SimpleNamespace(table=table, Record=Record, Status=Status)


@pytest.fixture
def models() -> Iterator[SimpleNamespace]:
    """A fresh mocked table plus the entity class bound to it, per benchmark."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        _create_table(client)
        table = Table(
            name=TABLE_NAME,
            indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
            client=client,
        )
        yield _build_models(table)


def sample_record(models: SimpleNamespace, n: int = 0) -> object:
    """Build one representative ``Record`` instance with a mix of types."""
    return models.Record(
        record_id=f"r{n}",
        org_id="acme",
        title=f"Record number {n}",
        status=Status.ACTIVE if n % 2 == 0 else Status.INACTIVE,
        login_count=n,
        amount=Decimal(f"{n}.99"),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        tags={"alpha", "beta", "gamma"},
        items=[f"item-{i}" for i in range(5)],
        metadata={"region": "us-east-1", "tier": "gold", "source": "import"},
    )
