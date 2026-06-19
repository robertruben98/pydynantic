"""Typed query builders and named access patterns."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .errors import ItemNotFoundError, MultipleResultsError
from .expressions import Condition, ExpressionContext
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

    # -- sort key conditions ------------------------------------------------
    def _with_sk(self, operator: str, *args: Any) -> QueryBuilder[E]:
        if self._key.sk_attr is None:
            raise ValueError(f"Key {self._key.name!r} has no sort key to filter on")
        self._sk = (operator, args)
        return self

    def eq(self, value: Any) -> QueryBuilder[E]:
        return self._with_sk("=", value)

    def lt(self, value: Any) -> QueryBuilder[E]:
        return self._with_sk("<", value)

    def lte(self, value: Any) -> QueryBuilder[E]:
        return self._with_sk("<=", value)

    def gt(self, value: Any) -> QueryBuilder[E]:
        return self._with_sk(">", value)

    def gte(self, value: Any) -> QueryBuilder[E]:
        return self._with_sk(">=", value)

    def begins_with(self, prefix: str) -> QueryBuilder[E]:
        return self._with_sk("begins_with", prefix)

    def between(self, low: Any, high: Any) -> QueryBuilder[E]:
        return self._with_sk("between", low, high)

    # -- modifiers ----------------------------------------------------------
    def filter(self, condition: Condition) -> QueryBuilder[E]:
        self._filter = condition if self._filter is None else (self._filter & condition)
        return self

    def limit(self, count: int) -> QueryBuilder[E]:
        self._limit = count
        return self

    def ascending(self) -> QueryBuilder[E]:
        self._forward = True
        return self

    def descending(self) -> QueryBuilder[E]:
        self._forward = False
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
        if self._filter is not None:
            params["FilterExpression"] = self._filter.compile(context)
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
            if remaining is not None:
                page_params["Limit"] = remaining
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

    def one_or_none(self) -> E | None:
        """Return the single match, ``None`` if none, error if more than one."""
        results = self.limit(2).all() if self._limit is None else self.all()
        if not results:
            return None
        if len(results) > 1:
            raise MultipleResultsError("Expected at most one item, found multiple")
        return results[0]

    def one(self) -> E:
        """Return the single match, raising if zero or more than one."""
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


class QueryNamespace(Generic[E]):
    """``Entity.query`` accessor exposing one builder per declared key."""

    def __init__(self, entity_cls: type[E]) -> None:
        self._entity = entity_cls

    def __getattr__(self, name: str) -> Callable[..., QueryBuilder[E]]:
        keys = self._entity.__keys__
        if name not in keys:
            raise AttributeError(
                f"{self._entity.__name__!r} has no access pattern named {name!r}"
            )
        key_def = keys[name]

        def builder(**pk_attrs: Any) -> QueryBuilder[E]:
            return QueryBuilder(self._entity, key_def, pk_attrs)

        return builder
