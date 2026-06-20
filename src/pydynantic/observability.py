"""Observability hooks for DynamoDB operations via a transparent client proxy.

Wrapping the single ``Table.client`` attribute instruments every DynamoDB call
made anywhere in the package, with no changes to the call sites themselves.
This module intentionally imports nothing from the rest of the package.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# DynamoDB operations we instrument. Any other attribute access passes through
# to the raw client unchanged.
_OPERATIONS: frozenset[str] = frozenset(
    {
        "put_item",
        "get_item",
        "delete_item",
        "update_item",
        "query",
        "scan",
        "batch_get_item",
        "batch_write_item",
        "transact_write_items",
    }
)


@dataclass(frozen=True)
class OperationEvent:
    """A single DynamoDB operation, reported to an :data:`OperationHook`."""

    operation: str
    table_name: str
    duration_ms: float
    success: bool
    exception: BaseException | None
    consumed_capacity: object | None


OperationHook = Callable[[OperationEvent], None]


class _ClientProxy:
    """Transparent proxy over a boto3 DynamoDB client that fires a hook.

    Known DynamoDB operations are wrapped to time the call, fire the hook, and
    re-raise any exception unchanged. All other attribute access is forwarded
    to the raw client untouched, so the proxy is behaviourally identical.
    """

    def __init__(self, client: Any, table_name: str, hook: OperationHook) -> None:
        self._client = client
        self._table_name = table_name
        self._hook = hook

    def _fire(self, event: OperationEvent) -> None:
        try:
            self._hook(event)
        except BaseException:  # noqa: BLE001 - a hook must never break the op.
            pass

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if name not in _OPERATIONS:
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                response = attr(*args, **kwargs)
            except BaseException as exc:
                duration_ms = (time.perf_counter() - start) * 1000.0
                self._fire(
                    OperationEvent(
                        operation=name,
                        table_name=self._table_name,
                        duration_ms=duration_ms,
                        success=False,
                        exception=exc,
                        consumed_capacity=None,
                    )
                )
                raise
            duration_ms = (time.perf_counter() - start) * 1000.0
            consumed_capacity: object | None = None
            if isinstance(response, dict):
                consumed_capacity = response.get("ConsumedCapacity")
            self._fire(
                OperationEvent(
                    operation=name,
                    table_name=self._table_name,
                    duration_ms=duration_ms,
                    success=True,
                    exception=None,
                    consumed_capacity=consumed_capacity,
                )
            )
            return response

        return wrapper
