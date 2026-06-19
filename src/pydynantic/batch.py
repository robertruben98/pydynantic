"""Batch read/write helpers with automatic chunking and retry of leftovers."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from .entity import Entity

E = TypeVar("E", bound="Entity")

#: DynamoDB hard limits per request.
BATCH_GET_LIMIT = 100
BATCH_WRITE_LIMIT = 25
_MAX_RETRIES = 8


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _backoff(attempt: int) -> None:
    # Exponential backoff, capped; attempt starts at 1.
    time.sleep(min(2 ** (attempt - 1) * 0.05, 1.0))


def batch_get(entity_cls: type[E], keys: list[Any], *, consistent: bool = False) -> list[E]:
    """Fetch many items by key, in chunks of 100, retrying ``UnprocessedKeys``."""
    from .entity import map_client_error

    table = entity_cls.__entity_table__
    client = table.client
    raw_keys = [entity_cls.build_key(entity_cls._coerce_key(k)) for k in keys]
    results: list[E] = []

    for chunk in _chunks(raw_keys, BATCH_GET_LIMIT):
        request: dict[str, Any] = {
            table.name: {"Keys": list(chunk), "ConsistentRead": consistent}
        }
        attempt = 0
        while request:
            try:
                response = client.batch_get_item(RequestItems=request)
            except ClientError as exc:
                raise map_client_error(exc) from exc
            for raw in response.get("Responses", {}).get(table.name, []):
                results.append(entity_cls.from_dynamo(raw))
            unprocessed = response.get("UnprocessedKeys") or {}
            if not unprocessed:
                break
            attempt += 1
            if attempt > _MAX_RETRIES:
                raise RuntimeError(
                    f"batch_get gave up after {attempt} retries with unprocessed keys"
                )
            _backoff(attempt)
            request = unprocessed
    return results


def batch_write(
    entity_cls: type[E],
    *,
    puts: list[E] | None = None,
    deletes: list[Any] | None = None,
) -> None:
    """Write/delete many items, in chunks of 25, retrying ``UnprocessedItems``."""
    from .entity import map_client_error

    table = entity_cls.__entity_table__
    client = table.client

    requests: list[dict[str, Any]] = []
    for item in puts or []:
        requests.append({"PutRequest": {"Item": item.to_dynamo()}})
    for key in deletes or []:
        raw_key = entity_cls.build_key(entity_cls._coerce_key(key))
        requests.append({"DeleteRequest": {"Key": raw_key}})

    for chunk in _chunks(requests, BATCH_WRITE_LIMIT):
        request: dict[str, Any] = {table.name: list(chunk)}
        attempt = 0
        while request:
            try:
                response = client.batch_write_item(RequestItems=request)
            except ClientError as exc:
                raise map_client_error(exc) from exc
            unprocessed = response.get("UnprocessedItems") or {}
            if not unprocessed:
                break
            attempt += 1
            if attempt > _MAX_RETRIES:
                raise RuntimeError(
                    f"batch_write gave up after {attempt} retries with unprocessed items"
                )
            _backoff(attempt)
            request = unprocessed
