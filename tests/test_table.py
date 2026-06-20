"""Tests for Table configuration, including the default boto3 client path."""

from __future__ import annotations

from typing import Any

from pydynantic import Table


def test_default_client_uses_boto3(monkeypatch: Any) -> None:
    """When no client is injected, Table builds ``boto3.client("dynamodb")``."""
    import boto3

    sentinel = object()
    calls: list[Any] = []

    def fake_client(service: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(service)
        return sentinel

    monkeypatch.setattr(boto3, "client", fake_client)
    table = Table("t", client=None)
    assert table.client is sentinel
    assert calls == ["dynamodb"]
