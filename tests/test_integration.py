"""Optional integration tests against a real DynamoDB Local instance.

These are deselected by default (see ``addopts`` in ``pyproject.toml``). Run a
local endpoint, then::

    DYNAMODB_ENDPOINT=http://localhost:8000 pytest -m integration

They exercise the exact same code paths as the moto-based unit tests, but with
a live DynamoDB-compatible server (e.g. ``amazon/dynamodb-local`` in Docker).
"""

from __future__ import annotations

import os
import uuid

import boto3
import pytest

from pydynantic import Entity, Table, key

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.integration


@pytest.fixture
def live_table() -> object:
    if not ENDPOINT:
        pytest.skip("set DYNAMODB_ENDPOINT to run integration tests")
    client = boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    name = f"pydynantic-it-{uuid.uuid4().hex[:8]}"
    client.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
    )
    client.get_waiter("table_exists").wait(TableName=name)
    try:
        yield Table(name=name, client=client)
    finally:
        client.delete_table(TableName=name)


def test_put_get_query_roundtrip(live_table: Table) -> None:
    class Widget(Entity, table=live_table, name="widget"):
        org_id: str
        widget_id: str
        label: str

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="WIDGET#{widget_id}")

    Widget.put(Widget(org_id="acme", widget_id="w1", label="Hello"))
    fetched = Widget.get(org_id="acme", widget_id="w1")
    assert fetched is not None and fetched.label == "Hello"

    results = Widget.query.primary(org_id="acme").begins_with("WIDGET#").all()
    assert [w.widget_id for w in results] == ["w1"]
