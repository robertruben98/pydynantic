"""Collections: retrieve several distinct entities from one partition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from .expressions import ExpressionContext
from .marshalling import deserialize_item

if TYPE_CHECKING:
    from .entity import Entity


def _bucket_name(entity_cls: type[Entity]) -> str:
    """Attribute name used to expose a member's items on a result (pluralised)."""
    return f"{entity_cls.__entity_name__}s"


class CollectionResult:
    """Holds the items of a collection query, bucketed per entity type."""

    def __init__(self, buckets: dict[str, list[Any]]) -> None:
        self._buckets = buckets

    def __getattr__(self, name: str) -> list[Any]:
        try:
            return self._buckets[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def all(self) -> list[Any]:
        """Every item across all buckets, in DynamoDB return order."""
        merged: list[Any] = []
        for items in self._buckets.values():
            merged.extend(items)
        return merged


class CollectionQuery:
    """A query over a single partition that may contain several entity types."""

    def __init__(self, collection_cls: type[Collection], pk_attrs: dict[str, Any]) -> None:
        members = collection_cls.members
        if not members:
            raise ValueError(f"{collection_cls.__name__} declares no members")
        primary = members[0].__primary_key__
        self._members = members
        self._table = members[0].__entity_table__
        self._pk_attr = primary.pk_attr
        self._pk_value = primary.build_pk(pk_attrs)

    def all(self) -> CollectionResult:
        """Run the query and return items bucketed by entity type."""
        context = ExpressionContext()
        key_condition = f"{context.name(self._pk_attr)} = {context.value(self._pk_value)}"
        params: dict[str, Any] = {
            "TableName": self._table.name,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeNames": context.names,
            "ExpressionAttributeValues": context.values,
        }

        buckets: dict[str, list[Any]] = {_bucket_name(member): [] for member in self._members}
        by_name = {member.__entity_name__: member for member in self._members}

        start_key: dict[str, Any] | None = None
        client = self._table.client
        while True:
            page_params = dict(params)
            if start_key is not None:
                page_params["ExclusiveStartKey"] = start_key
            response = client.query(**page_params)
            for raw in response.get("Items", []):
                data = deserialize_item(raw)
                entity_name = data.get("__entity__")
                member = by_name.get(entity_name) if isinstance(entity_name, str) else None
                if member is None:
                    continue
                buckets[_bucket_name(member)].append(member.from_dynamo(raw))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        return CollectionResult(buckets)


class Collection:
    """Base class for a set of entities sharing a partition.

    Declare ``members = [User, Membership, Invoice]`` on the subclass; all
    members must compose the same partition key. Query a partition with
    ``OrgData.query(org_id="acme").all()`` and read results as ``result.users``,
    ``result.invoices`` (the entity name pluralised).
    """

    members: ClassVar[list[type[Entity]]] = []

    @classmethod
    def query(cls, **pk_attrs: Any) -> CollectionQuery:
        return CollectionQuery(cls, pk_attrs)
