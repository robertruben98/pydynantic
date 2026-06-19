"""Physical table configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .entity import Entity


@dataclass(frozen=True)
class Index:
    """A secondary index's physical key attribute names."""

    pk: str
    sk: str | None = None


class Table:
    """Configuration for a single physical DynamoDB table.

    The boto3 client is injected (defaulting to ``boto3.client("dynamodb")``)
    so credentials, region and endpoint stay the caller's concern and tests can
    inject a mocked client.
    """

    def __init__(
        self,
        name: str,
        *,
        pk: str = "PK",
        sk: str | None = "SK",
        indexes: dict[str, dict[str, str]] | None = None,
        client: Any = None,
    ) -> None:
        self.name = name
        self.pk = pk
        self.sk = sk
        self.indexes: dict[str, Index] = {
            index_name: Index(**spec) for index_name, spec in (indexes or {}).items()
        }
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self.client = client
        # entity name -> entity class, used to discriminate items on read.
        self._entities: dict[str, type[Entity]] = {}

    def register(self, entity_cls: type[Entity]) -> None:
        """Register an entity so items can be routed back to it by ``__entity__``."""
        self._entities[entity_cls.__entity_name__] = entity_cls

    def entity_for(self, name: str) -> type[Entity] | None:
        """Look up a registered entity class by its discriminator name."""
        return self._entities.get(name)
