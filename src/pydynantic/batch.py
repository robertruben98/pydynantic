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


def batch_get(
    entity_cls: type[E],
    keys: list[Any],
    *,
    consistent: bool = False,
    attributes: list[str] | None = None,
) -> list[E]:
    """Fetch many items by key, in chunks of 100, retrying ``UnprocessedKeys``.

    ``attributes`` limits the response to a projection of attribute paths;
    omitted fields fall back to their model defaults (or fail validation if
    required), so include everything the entity needs to construct.
    """
    from .entity import map_client_error
    from .expressions import ExpressionContext

    table = entity_cls.__entity_table__
    client = table.client

    context = ExpressionContext()
    projection = ", ".join(context.name(a) for a in attributes) if attributes else None
    # DynamoDB rejects a BatchGetItem with duplicate keys; dedupe while
    # preserving first-seen order.
    seen: set[str] = set()
    raw_keys: list[dict[str, Any]] = []
    for k in keys:
        raw = entity_cls.build_key(entity_cls._coerce_key(k))
        marker = repr(sorted(raw.items()))
        if marker in seen:
            continue
        seen.add(marker)
        raw_keys.append(raw)
    results: list[E] = []

    for chunk in _chunks(raw_keys, BATCH_GET_LIMIT):
        table_request: dict[str, Any] = {"Keys": list(chunk), "ConsistentRead": consistent}
        if projection is not None:
            table_request["ProjectionExpression"] = projection
            table_request["ExpressionAttributeNames"] = context.names
        request: dict[str, Any] = {table.name: table_request}
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
                    f"batch_get gave up after {attempt} retries with unprocessed keys; "
                    "DynamoDB is likely throttling the request, so reduce the batch size "
                    "or provision more read capacity and retry."
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
                    f"batch_write gave up after {attempt} retries with unprocessed items; "
                    "DynamoDB is likely throttling the request, so reduce the batch size "
                    "or provision more write capacity and retry."
                )
            _backoff(attempt)
            request = unprocessed
