"""Typed query builders and named access patterns."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .errors import ItemNotFoundError, MultipleResultsError
from .expressions import Condition, ExpressionContext, F
from .keys import KeyDefinition
from .pagination import Page, decode_cursor, encode_cursor

if TYPE_CHECKING:
    from .entity import Entity

E = TypeVar("E", bound="Entity")

# Sort-key comparison operators accepted in a KeyConditionExpression.
_SK_COMPARATORS = {"=", "<", "<=", ">", ">="}


class QueryBuilder(Generic[E]):
    """Fluent builder for a query against one declared key (primary or GSI)."""

    def __init__(
        self, entity_cls: type[E], key_def: KeyDefinition, pk_attrs: dict[str, Any]
    ) -> None:
        self._entity = entity_cls
        self._key = key_def
        self._pk_value = key_def.build_pk(pk_attrs)
        self._sk: tuple[str, tuple[Any, ...]] | None = None
        self._filter: Condition | None = None
        self._limit: int | None = None
        self._forward = True
        self._projection: list[str] | None = None
        self._consistent = False

    # -- sort key conditions ------------------------------------------------
    def _with_sk(self, operator: str, *args: Any) -> QueryBuilder[E]:
        if self._key.sk_attr is None:
            raise ValueError(
                f"Key {self._key.name!r} has no sort key to filter on; declare an sk= "
                "template on this key or query by partition key alone."
            )
        self._sk = (operator, args)
        return self

    def eq(self, value: Any) -> QueryBuilder[E]:
        """Match items whose sort key equals ``value``."""
        return self._with_sk("=", value)

    def lt(self, value: Any) -> QueryBuilder[E]:
        """Match items whose sort key is less than ``value``."""
        return self._with_sk("<", value)

    def lte(self, value: Any) -> QueryBuilder[E]:
        """Match items whose sort key is less than or equal to ``value``."""
        return self._with_sk("<=", value)

    def gt(self, value: Any) -> QueryBuilder[E]:
        """Match items whose sort key is greater than ``value``."""
        return self._with_sk(">", value)

    def gte(self, value: Any) -> QueryBuilder[E]:
        """Match items whose sort key is greater than or equal to ``value``."""
        return self._with_sk(">=", value)

    def begins_with(self, prefix: str) -> QueryBuilder[E]:
        """Match items whose sort key starts with ``prefix``."""
        return self._with_sk("begins_with", prefix)

    def between(self, low: Any, high: Any) -> QueryBuilder[E]:
        """Match items whose sort key falls within ``[low, high]`` inclusive."""
        return self._with_sk("between", low, high)

    # -- modifiers ----------------------------------------------------------
    def filter(self, condition: Condition) -> QueryBuilder[E]:
        """Add a post-read filter expression; chained calls are AND-combined."""
        self._filter = condition if self._filter is None else (self._filter & condition)
        return self

    def limit(self, count: int) -> QueryBuilder[E]:
        """Cap the number of items DynamoDB evaluates per page at ``count``."""
        self._limit = count
        return self

    def attributes(self, names: list[str]) -> QueryBuilder[E]:
        """Project only ``names``; omitted fields fall back to model defaults."""
        self._projection = names
        return self

    def ascending(self) -> QueryBuilder[E]:
        """Return results in ascending sort-key order (the DynamoDB default)."""
        self._forward = True
        return self

    def descending(self) -> QueryBuilder[E]:
        """Return results in descending sort-key order."""
        self._forward = False
        return self

    def consistent(self, value: bool = True) -> QueryBuilder[E]:
        """Request a strongly consistent read. Mirrors ``get(consistent=...)``.

        GSIs only support eventually consistent reads, so requesting a
        consistent read against an index is rejected eagerly.
        """
        if value and self._key.index is not None:
            raise ValueError(
                f"Index {self._key.index!r} (GSI) does not support consistent reads; "
                "drop the consistent_read() call or query the table's primary key instead."
            )
        self._consistent = value
        return self

    # -- request building ---------------------------------------------------
    def _key_condition(self, context: ExpressionContext) -> str:
        pk_name = context.name(self._key.pk_attr)
        expression = f"{pk_name} = {context.value(self._pk_value)}"
        if self._sk is not None and self._key.sk_attr is not None:
            operator, args = self._sk
            sk_name = context.name(self._key.sk_attr)
            if operator == "begins_with":
                expression += f" AND begins_with({sk_name}, {context.value(args[0])})"
            elif operator == "between":
                low, high = context.value(args[0]), context.value(args[1])
                expression += f" AND {sk_name} BETWEEN {low} AND {high}"
            elif operator in _SK_COMPARATORS:
                expression += f" AND {sk_name} {operator} {context.value(args[0])}"
        return expression

    def _build_params(self) -> dict[str, Any]:
        context = ExpressionContext()
        params: dict[str, Any] = {
            "TableName": self._entity.__entity_table__.name,
            "KeyConditionExpression": self._key_condition(context),
        }
        if self._key.index is not None:
            params["IndexName"] = self._key.index
        if self._consistent:
            params["ConsistentRead"] = True
        if self._filter is not None:
            params["FilterExpression"] = self._filter.compile(context)
        if self._projection:
            params["ProjectionExpression"] = ", ".join(context.name(a) for a in self._projection)
        if not self._forward:
            params["ScanIndexForward"] = False
        params["ExpressionAttributeNames"] = context.names
        params["ExpressionAttributeValues"] = context.values
        return params

    # -- terminals ----------------------------------------------------------
    def iter(self) -> Iterator[E]:
        """Lazily iterate all matching items, paginating transparently."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        remaining = self._limit
        start_key: dict[str, Any] | None = None
        while True:
            page_params = dict(params)
            # DynamoDB's Limit caps items *examined*, not items returned. With a
            # FilterExpression the two differ, so shrinking Limit to the post-filter
            # remaining narrows the scan window each page and over-issues round-trips.
            # Without a filter, examined == returned, so shrink to exactly remaining.
            if remaining is not None:
                page_params["Limit"] = self._limit if self._filter is not None else remaining
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.query(**page_params)
            for raw in response.get("Items", []):
                yield self._entity.from_dynamo(raw)
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return

    def all(self) -> list[E]:
        """Return every matching item as a list."""
        return list(self.iter())

    def first(self) -> E | None:
        """Return the first matching item, or ``None``."""
        for item in self.iter():
            return item
        return None

    def _fetch_two(self) -> list[E]:
        """Fetch up to two matching items, ignoring any user ``.limit()``.

        Mirrors :meth:`iter`'s pagination loop with an effective ``Limit`` of 2
        so multiplicity can always be detected, without mutating ``self._limit``.
        """
        client = self._entity.__entity_table__.client
        params = self._build_params()
        remaining = 2
        results: list[E] = []
        start_key: dict[str, Any] | None = None
        while True:
            page_params = dict(params)
            page_params["Limit"] = remaining
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.query(**page_params)
            for raw in response.get("Items", []):
                results.append(self._entity.from_dynamo(raw))
                remaining -= 1
                if remaining <= 0:
                    return results
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return results

    def one_or_none(self) -> E | None:
        """Return the single match, ``None`` if none, error if more than one.

        Any user ``.limit()`` is ignored: this always probes for a second item
        so the "multiple results" case is never silently masked.
        """
        results = self._fetch_two()
        if not results:
            return None
        if len(results) > 1:
            raise MultipleResultsError("Expected at most one item, found multiple")
        return results[0]

    def one(self) -> E:
        """Return the single match, raising if zero or more than one.

        Any user ``.limit()`` is ignored: this always probes for a second item
        so the "multiple results" case is never silently masked.
        """
        result = self.one_or_none()
        if result is None:
            raise ItemNotFoundError("Expected exactly one item, found none")
        return result

    def page(self, cursor: str | None = None) -> Page[E]:
        """Return a single page of results plus an opaque next-page cursor."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        if self._limit is not None:
            params["Limit"] = self._limit
        start_key = decode_cursor(cursor)
        if start_key is not None:
            params["ExclusiveStartKey"] = start_key
        response = client.query(**params)
        items = [self._entity.from_dynamo(raw) for raw in response.get("Items", [])]
        return Page(items=items, cursor=encode_cursor(response.get("LastEvaluatedKey")))

    def count(self) -> int:
        """Count matching items server-side without materialising them."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        params["Select"] = "COUNT"
        params.pop("ProjectionExpression", None)
        total = 0
        start_key: dict[str, Any] | None = None
        while True:
            page_params = dict(params)
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.query(**page_params)
            total += int(response.get("Count", 0))
            # Honour .limit() like the other terminals: cap the reported count.
            if self._limit is not None and total >= self._limit:
                return self._limit
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return total


class QueryNamespace(Generic[E]):
    """``Entity.query`` accessor exposing one builder per declared key."""

    def __init__(self, entity_cls: type[E]) -> None:
        self._entity = entity_cls

    def __getattr__(self, name: str) -> Callable[..., QueryBuilder[E]]:
        keys = self._entity.__keys__
        if name not in keys:
            raise AttributeError(
                f"{self._entity.__name__!r} has no access pattern named {name!r}; "
                f"declared keys are {sorted(keys)}."
            )
        key_def = keys[name]

        def builder(**pk_attrs: Any) -> QueryBuilder[E]:
            return QueryBuilder(self._entity, key_def, pk_attrs)

        return builder


class ScanBuilder(Generic[E]):
    """Fluent builder for a full-table scan restricted to one entity type."""

    def __init__(self, entity_cls: type[E]) -> None:
        self._entity = entity_cls
        self._filter: Condition | None = None
        self._limit: int | None = None
        self._projection: list[str] | None = None

    def filter(self, condition: Condition) -> ScanBuilder[E]:
        """Add a filter expression applied after the scan; chained calls AND-combine."""
        self._filter = condition if self._filter is None else (self._filter & condition)
        return self

    def limit(self, count: int) -> ScanBuilder[E]:
        """Cap the number of items DynamoDB evaluates per page at ``count``."""
        self._limit = count
        return self

    def attributes(self, names: list[str]) -> ScanBuilder[E]:
        """Project only ``names``; omitted fields fall back to model defaults."""
        self._projection = names
        return self

    def _build_params(self) -> dict[str, Any]:
        from .entity import ENTITY_ATTR

        context = ExpressionContext()
        # Restrict the scan to this entity via the discriminator marker.
        discriminator: Condition = F(ENTITY_ATTR) == self._entity.__entity_name__
        full_filter = discriminator if self._filter is None else (discriminator & self._filter)
        params: dict[str, Any] = {
            "TableName": self._entity.__entity_table__.name,
            "FilterExpression": full_filter.compile(context),
        }
        if self._projection:
            params["ProjectionExpression"] = ", ".join(context.name(a) for a in self._projection)
        params["ExpressionAttributeNames"] = context.names
        params["ExpressionAttributeValues"] = context.values
        return params

    def iter(self) -> Iterator[E]:
        """Lazily iterate matching items, paginating transparently."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        remaining = self._limit
        start_key: dict[str, Any] | None = None
        while True:
            page_params = dict(params)
            # A scan always carries the entity discriminator as a FilterExpression,
            # so examined != returned. Cap each page at the constant requested limit
            # rather than the shrinking post-filter remaining (which over-issues
            # round-trips); stop yielding once the limit is reached.
            if remaining is not None:
                page_params["Limit"] = self._limit
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.scan(**page_params)
            for raw in response.get("Items", []):
                yield self._entity.from_dynamo(raw)
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return

    def all(self) -> list[E]:
        """Return every matching item as a list."""
        return list(self.iter())

    def first(self) -> E | None:
        """Return the first matching item, or ``None``."""
        for item in self.iter():
            return item
        return None

    def page(self, cursor: str | None = None) -> Page[E]:
        """Return a single page of results plus an opaque next-page cursor."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        if self._limit is not None:
            params["Limit"] = self._limit
        start_key = decode_cursor(cursor)
        if start_key is not None:
            params["ExclusiveStartKey"] = start_key
        response = client.scan(**params)
        items = [self._entity.from_dynamo(raw) for raw in response.get("Items", [])]
        return Page(items=items, cursor=encode_cursor(response.get("LastEvaluatedKey")))

    def count(self) -> int:
        """Count matching items server-side without materialising them."""
        client = self._entity.__entity_table__.client
        params = self._build_params()
        params["Select"] = "COUNT"
        params.pop("ProjectionExpression", None)
        total = 0
        start_key: dict[str, Any] | None = None
        while True:
            page_params = dict(params)
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.scan(**page_params)
            total += int(response.get("Count", 0))
            # Honour .limit() like the other terminals: cap the reported count.
            if self._limit is not None and total >= self._limit:
                return self._limit
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return total
