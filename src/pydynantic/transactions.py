"""Transactional writes mapped onto ``TransactWriteItems``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from botocore.exceptions import ClientError

from .errors import PydynanticError
from .expressions import Condition, ExpressionContext

if TYPE_CHECKING:
    from .entity import Entity
    from .table import Table

E = TypeVar("E", bound="Entity")

#: Maximum number of actions allowed in a single transaction.
MAX_TRANSACTION_ITEMS = 100


class Transaction:
    """Accumulates write actions and flushes them atomically on ``commit``."""

    def __init__(self, table: Table) -> None:
        self.table = table
        self._items: list[dict[str, Any]] = []

    def _check_capacity(self) -> None:
        if len(self._items) >= MAX_TRANSACTION_ITEMS:
            raise PydynanticError(
                f"A transaction may contain at most {MAX_TRANSACTION_ITEMS} actions"
            )

    @staticmethod
    def _attach_condition(
        target: dict[str, Any], condition: Condition | None, context: ExpressionContext
    ) -> None:
        if condition is not None:
            target["ConditionExpression"] = condition.compile(context)
        if context.names:
            target["ExpressionAttributeNames"] = context.names
        if context.values:
            target["ExpressionAttributeValues"] = context.values

    def put(self, item: Entity, *, condition: Condition | None = None) -> None:
        """Queue a ``Put`` action."""
        self._check_capacity()
        action: dict[str, Any] = {
            "TableName": item.__entity_table__.name,
            "Item": item.to_dynamo(),
        }
        self._attach_condition(action, condition, ExpressionContext())
        self._items.append({"Put": action})

    def delete(
        self, entity_cls: type[E], *, key: Any, condition: Condition | None = None
    ) -> None:
        """Queue a ``Delete`` action."""
        self._check_capacity()
        action: dict[str, Any] = {
            "TableName": entity_cls._table_name(),
            "Key": entity_cls.build_key(entity_cls._coerce_key(key)),
        }
        self._attach_condition(action, condition, ExpressionContext())
        self._items.append({"Delete": action})

    def condition_check(
        self, entity_cls: type[E], *, key: Any, condition: Condition
    ) -> None:
        """Queue a ``ConditionCheck`` action (no write, just a guard)."""
        self._check_capacity()
        context = ExpressionContext()
        action: dict[str, Any] = {
            "TableName": entity_cls._table_name(),
            "Key": entity_cls.build_key(entity_cls._coerce_key(key)),
        }
        self._attach_condition(action, condition, context)
        self._items.append({"ConditionCheck": action})

    def update(
        self,
        entity_cls: type[E],
        *,
        key: Any,
        set: dict[str, Any] | None = None,
        remove: list[str] | None = None,
        add: dict[str, Any] | None = None,
        delete: dict[str, Any] | None = None,
        condition: Condition | None = None,
    ) -> None:
        """Queue an ``Update`` action."""
        self._check_capacity()
        context = ExpressionContext()
        clauses: list[str] = []
        if set:
            parts = [f"{context.name(k)} = {context.value(v)}" for k, v in set.items()]
            clauses.append("SET " + ", ".join(parts))
        if remove:
            clauses.append("REMOVE " + ", ".join(context.name(k) for k in remove))
        if add:
            parts = [f"{context.name(k)} {context.value(v)}" for k, v in add.items()]
            clauses.append("ADD " + ", ".join(parts))
        if delete:
            parts = [f"{context.name(k)} {context.value(v)}" for k, v in delete.items()]
            clauses.append("DELETE " + ", ".join(parts))
        if not clauses:
            raise PydynanticError("tx.update() requires at least one write clause")

        action: dict[str, Any] = {
            "TableName": entity_cls._table_name(),
            "Key": entity_cls.build_key(entity_cls._coerce_key(key)),
            "UpdateExpression": " ".join(clauses),
        }
        if condition is not None:
            action["ConditionExpression"] = condition.compile(context)
        if context.names:
            action["ExpressionAttributeNames"] = context.names
        if context.values:
            action["ExpressionAttributeValues"] = context.values
        self._items.append({"Update": action})

    def commit(self) -> None:
        """Send all queued actions as a single ``TransactWriteItems`` call."""
        from .entity import map_client_error

        if not self._items:
            return
        try:
            self.table.client.transact_write_items(TransactItems=self._items)
        except ClientError as exc:
            raise map_client_error(exc) from exc


@contextmanager
def transaction(table: Table) -> Iterator[Transaction]:
    """Context manager that commits queued actions on a clean exit.

    If the ``with`` block raises, ``commit`` is never reached, so no actions are
    sent (rollback). If a queued condition fails at commit time, DynamoDB
    cancels the whole transaction atomically.
    """
    tx = Transaction(table)
    yield tx
    tx.commit()
