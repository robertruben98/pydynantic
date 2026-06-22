"""The :class:`Entity` base class and its metaclass.

Entities are Pydantic models that additionally carry single-table metadata:
their discriminator name, key templates (declared on an inner ``Meta`` class),
and the table they live in. The metaclass wires all of that up and exposes the
typed CRUD / query surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, cast

from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError
from pydantic._internal._model_construction import ModelMetaclass
from typing_extensions import Self

from .attributes import (
    is_created_at_field,
    is_ttl_field,
    is_updated_at_field,
    is_version_field,
)
from .errors import (
    ConditionCheckFailedError,
    KeyTemplateError,
    OptimisticLockError,
    PydynanticError,
    TransactionCanceledError,
    ValidationError,
)
from .expressions import Condition, ExpressionContext, F, attr_not_exists
from .keys import KeyDefinition, template_fields
from .marshalling import Item, deserialize_item, serialize, serialize_item
from .query import QueryNamespace

if TYPE_CHECKING:
    from .query import ScanBuilder
    from .table import Table

#: Reserved attribute used to discriminate entities when deserializing.
ENTITY_ATTR = "__entity__"

E = TypeVar("E", bound="Entity")

#: ``ReturnValues`` values DynamoDB accepts on ``PutItem`` / ``DeleteItem``.
_ALLOWED_RETURN_VALUES = {"NONE", "ALL_OLD"}


def map_client_error(exc: ClientError, *, versioned: bool = False) -> PydynanticError:
    """Translate a botocore ``ClientError`` into the pydynantic hierarchy."""
    code = exc.response.get("Error", {}).get("Code", "")
    message = exc.response.get("Error", {}).get("Message", str(exc))
    if code == "ConditionalCheckFailedException":
        if versioned:
            return OptimisticLockError(
                f"{message} (the item was modified concurrently; re-read it and retry the write)"
            )
        return ConditionCheckFailedError(message)
    if code == "TransactionCanceledException":
        reasons = exc.response.get("CancellationReasons", [])
        return TransactionCanceledError(message, reasons)
    return PydynanticError(f"{code}: {message}")


def _compile_condition(condition: Condition, context: ExpressionContext) -> str:
    return condition.compile(context)


class _QueryAccessor:
    """Descriptor returning a typed :class:`QueryNamespace` for the owning class."""

    def __get__(self, instance: object, owner: type[E]) -> QueryNamespace[E]:
        return QueryNamespace(owner)


class EntityMeta(ModelMetaclass):
    """Metaclass that binds key templates and registers entities with a table."""

    def __new__(
        mcs,
        cls_name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        name: str | None = None,
        table: Table | None = None,
        **kwargs: Any,
    ) -> type:
        meta = namespace.get("Meta")
        created = super().__new__(mcs, cls_name, bases, namespace, **kwargs)

        # The bare ``Entity`` base has neither name nor table; leave it alone.
        if name is None and table is None:
            return created
        if name is None or table is None:
            raise TypeError(
                f"{cls_name}: entities require both 'name=' and 'table=' keyword arguments"
            )

        cls = cast("type[Entity]", created)

        cls.__entity_name__ = name
        cls.__entity_table__ = table

        keys: dict[str, KeyDefinition] = {}
        primary: KeyDefinition | None = None
        if meta is not None:
            for attr_name, value in vars(meta).items():
                if not isinstance(value, KeyDefinition):
                    continue
                value.bind(attr_name, table)
                missing = value.referenced_fields - set(cls.model_fields)
                if missing:
                    raise KeyTemplateError(
                        f"{cls_name}.Meta.{attr_name} references undeclared "
                        f"attribute(s): {sorted(missing)}"
                    )
                keys[attr_name] = value
                if value.index is None:
                    if primary is not None:
                        raise KeyTemplateError(f"{cls_name}: more than one primary key declared")
                    primary = value

        if primary is None:
            raise KeyTemplateError(f"{cls_name}: no primary key declared in Meta")

        cls.__keys__ = keys
        cls.__primary_key__ = primary
        cls.__key_attrs__ = list(
            dict.fromkeys(
                template_fields(primary.pk_template) + template_fields(primary.sk_template or "")
            )
        )

        cls.__version_field__ = None
        for field_name, field_info in cls.model_fields.items():
            if is_version_field(field_info):
                cls.__version_field__ = field_name
                break

        cls.__ttl_field__ = None
        for field_name, field_info in cls.model_fields.items():
            if is_ttl_field(field_info):
                if cls.__ttl_field__ is not None:
                    raise TypeError(f"{cls_name}: more than one TTL field declared")
                cls.__ttl_field__ = field_name

        cls.__created_field__ = None
        for field_name, field_info in cls.model_fields.items():
            if is_created_at_field(field_info):
                if cls.__created_field__ is not None:
                    raise TypeError(f"{cls_name}: more than one created_at field declared")
                cls.__created_field__ = field_name

        cls.__updated_field__ = None
        for field_name, field_info in cls.model_fields.items():
            if is_updated_at_field(field_info):
                if cls.__updated_field__ is not None:
                    raise TypeError(f"{cls_name}: more than one updated_at field declared")
                cls.__updated_field__ = field_name

        table.register(cls)
        return cls


class Entity(BaseModel, metaclass=EntityMeta):
    """Base class for single-table entities.

    Subclass with ``class User(Entity, table=table, name="user"): ...`` and
    declare key templates on an inner ``Meta`` class via :func:`pydynantic.key`.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # Populated by the metaclass for concrete subclasses.
    __entity_name__: ClassVar[str]
    __entity_table__: ClassVar[Table]
    __keys__: ClassVar[dict[str, KeyDefinition]]
    __primary_key__: ClassVar[KeyDefinition]
    __key_attrs__: ClassVar[list[str]]
    __version_field__: ClassVar[str | None]
    __ttl_field__: ClassVar[str | None]
    __created_field__: ClassVar[str | None]
    __updated_field__: ClassVar[str | None]

    query: ClassVar[_QueryAccessor] = _QueryAccessor()

    # -- (de)serialization --------------------------------------------------
    def to_dynamo(self) -> Item:
        """Build the full DynamoDB item (attributes + composed keys + marker)."""
        cls = type(self)
        attrs = {field_name: getattr(self, field_name) for field_name in cls.model_fields}
        item = serialize_item(attrs)
        ttl_field = cls.__ttl_field__
        if ttl_field is not None:
            ttl_value = attrs[ttl_field]
            if ttl_value is not None:
                if isinstance(ttl_value, datetime):
                    epoch = int(ttl_value.timestamp())
                else:
                    epoch = int(ttl_value)
                item[ttl_field] = serialize(epoch)
        for key_def in cls.__keys__.values():
            for physical_name, value in key_def.key_attributes(attrs).items():
                item[physical_name] = serialize(value)
        item[ENTITY_ATTR] = serialize(cls.__entity_name__)
        return item

    @classmethod
    def from_dynamo(cls, item: dict[str, Any]) -> Self:
        """Deserialize a raw DynamoDB item into an entity instance."""
        data = deserialize_item(item)
        try:
            return cls.model_validate(data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

    # -- helpers ------------------------------------------------------------
    @classmethod
    def _client(cls) -> Any:
        return cls.__entity_table__.client

    @classmethod
    def _table_name(cls) -> str:
        return cls.__entity_table__.name

    @classmethod
    def _coerce_key(cls, key: Any) -> dict[str, Any]:
        if isinstance(key, dict):
            return key
        if isinstance(key, (tuple, list)):
            return dict(zip(cls.__key_attrs__, key, strict=False))
        raise TypeError(
            f"Cannot interpret {key!r} as a key for {cls.__name__}; pass a dict of "
            f"key attributes, or a tuple/list ordered as {list(cls.__key_attrs__)}."
        )

    @classmethod
    def build_key(cls, attrs: dict[str, Any]) -> Item:
        """Build the primary-key portion of an item from attribute values."""
        primary = cls.__primary_key__
        key: Item = {primary.pk_attr: serialize(primary.build_pk(attrs))}
        sort_value = primary.build_sk(attrs)
        if sort_value is not None and primary.sk_attr is not None:
            key[primary.sk_attr] = serialize(sort_value)
        return key

    # -- CRUD ---------------------------------------------------------------
    @classmethod
    def put(
        cls,
        item: Self,
        *,
        condition: Condition | None = None,
        return_values: str = "NONE",
    ) -> Self:
        """Create or replace an item. Supports optimistic locking and conditions.

        ``put`` always returns the **written** item (the object you passed in),
        so ``put(x) is x``. ``return_values="ALL_OLD"`` asks DynamoDB to surface
        the pre-write stored state at the API level, but ``put``'s return value
        is unchanged — and with optimistic locking the returned object carries
        the bumped version. Only ``NONE`` and ``ALL_OLD`` are valid.
        """
        if return_values not in _ALLOWED_RETURN_VALUES:
            raise PydynanticError(
                f"return_values must be one of {sorted(_ALLOWED_RETURN_VALUES)}, "
                f"got {return_values!r}"
            )

        version_field = cls.__version_field__
        versioned = version_field is not None
        current = 0
        if version_field is not None:
            current = getattr(item, version_field)
            setattr(item, version_field, current + 1)
            lock = attr_not_exists(cls.__primary_key__.pk_attr) | (F(version_field) == current)
            condition = lock if condition is None else (condition & lock)

        # Auto-timestamps: stamp created_at on first write, updated_at on every
        # write. Capture prior values so a failed write can be rolled back.
        now = datetime.now(timezone.utc)
        created_field = cls.__created_field__
        updated_field = cls.__updated_field__
        prior_created = prior_updated = None
        if created_field is not None:
            prior_created = getattr(item, created_field)
            if prior_created is None:
                setattr(item, created_field, now)
        if updated_field is not None:
            prior_updated = getattr(item, updated_field)
            setattr(item, updated_field, now)

        params: dict[str, Any] = {"TableName": cls._table_name(), "Item": item.to_dynamo()}
        if return_values != "NONE":
            params["ReturnValues"] = return_values
        if condition is not None:
            context = ExpressionContext()
            params["ConditionExpression"] = _compile_condition(condition, context)
            params["ExpressionAttributeNames"] = context.names
            if context.values:
                params["ExpressionAttributeValues"] = context.values
        try:
            cls._client().put_item(**params)
        except ClientError as exc:
            if version_field is not None:
                # The write never landed; undo the in-memory bump so the caller's
                # object still reflects the stored version and can be retried.
                setattr(item, version_field, current)
            # Likewise roll back the timestamp stamps so a retry re-stamps cleanly.
            if created_field is not None:
                setattr(item, created_field, prior_created)
            if updated_field is not None:
                setattr(item, updated_field, prior_updated)
            raise map_client_error(exc, versioned=versioned) from exc
        return item

    @classmethod
    def get(
        cls,
        *,
        consistent: bool = False,
        attributes: list[str] | None = None,
        **key_attrs: Any,
    ) -> Self | None:
        """Fetch an item by its primary key, or ``None`` if it does not exist.

        ``attributes`` limits the response to a projection of attribute paths;
        omitted fields fall back to their model defaults (or fail validation if
        required), so include everything the entity needs to construct.
        """
        params: dict[str, Any] = {
            "TableName": cls._table_name(),
            "Key": cls.build_key(key_attrs),
            "ConsistentRead": consistent,
        }
        if attributes:
            context = ExpressionContext()
            params["ProjectionExpression"] = ", ".join(context.name(a) for a in attributes)
            params["ExpressionAttributeNames"] = context.names
        response = cls._client().get_item(**params)
        item = response.get("Item")
        if not item:
            return None
        return cls.from_dynamo(item)

    @classmethod
    def get_or_raise(
        cls,
        *,
        consistent: bool = False,
        attributes: list[str] | None = None,
        **key_attrs: Any,
    ) -> Self:
        """Like :meth:`get` but raises :class:`ItemNotFoundError` when missing.

        Accepts the same ``consistent`` and ``attributes`` read options as
        :meth:`get`.
        """
        from .errors import ItemNotFoundError

        result = cls.get(consistent=consistent, attributes=attributes, **key_attrs)
        if result is None:
            raise ItemNotFoundError(f"{cls.__name__} not found for {key_attrs}")
        return result

    @classmethod
    def delete(
        cls,
        *,
        condition: Condition | None = None,
        return_values: str = "NONE",
        **key_attrs: Any,
    ) -> Self | None:
        """Delete an item by its primary key.

        With ``return_values="ALL_OLD"`` the deleted item is returned (or
        ``None`` if it did not exist); otherwise ``delete`` returns ``None``.
        Only ``NONE`` and ``ALL_OLD`` are valid.
        """
        if return_values not in _ALLOWED_RETURN_VALUES:
            raise PydynanticError(
                f"return_values must be one of {sorted(_ALLOWED_RETURN_VALUES)}, "
                f"got {return_values!r}"
            )

        params: dict[str, Any] = {
            "TableName": cls._table_name(),
            "Key": cls.build_key(key_attrs),
        }
        if return_values != "NONE":
            params["ReturnValues"] = return_values
        if condition is not None:
            context = ExpressionContext()
            params["ConditionExpression"] = _compile_condition(condition, context)
            params["ExpressionAttributeNames"] = context.names
            if context.values:
                params["ExpressionAttributeValues"] = context.values
        try:
            response = cls._client().delete_item(**params)
        except ClientError as exc:
            raise map_client_error(exc) from exc

        if return_values == "NONE":
            return None
        attributes = response.get("Attributes")
        if not attributes:
            return None
        return cls.from_dynamo(attributes)

    @classmethod
    def update(
        cls,
        *,
        set: dict[str, Any] | None = None,
        remove: list[str] | None = None,
        add: dict[str, Any] | None = None,
        delete: dict[str, Any] | None = None,
        condition: Condition | None = None,
        expected_version: int | None = None,
        return_values: str = "ALL_NEW",
        **key_attrs: Any,
    ) -> Self | None:
        """Apply a partial update via a generated ``UpdateExpression``.

        ``set`` assigns attributes, ``remove`` deletes them, ``add`` performs
        atomic numeric/set additions, ``delete`` removes elements from sets.
        Any GSI key whose source attributes change is recomputed automatically.

        On a versioned entity, pass ``expected_version`` to guard the write with
        the version you last read: a concurrent change raises
        :class:`~pydynantic.OptimisticLockError` instead of silently overwriting
        it. The stored ``version`` is always incremented regardless.
        """
        version_field = cls.__version_field__
        if expected_version is not None and version_field is None:
            raise ValueError(
                "expected_version= requires a version_attr() field on "
                f"{cls.__name__}; this entity is not versioned."
            )

        # The physical primary key is immutable: changing an attribute that feeds
        # it would desync the body from the stored Key, so refuse rather than
        # write a half-correct item (delete + re-put to move an item).
        mutated = {*(set or {}), *(remove or []), *(add or {}), *(delete or {})}
        pk_sources = cls.__primary_key__.referenced_fields & mutated
        if pk_sources:
            raise PydynanticError(
                f"update() cannot change {sorted(pk_sources)}: these feed the "
                f"immutable primary key of {cls.__name__}. Delete and re-create "
                "the item to move it."
            )

        context = ExpressionContext()
        set_items: dict[str, Any] = dict(set or {})

        # Auto-stamp updated_at unless the caller set it explicitly. Done before
        # the GSI recompute so an updated_at-fed index recomputes from the stamp.
        updated_field = cls.__updated_field__
        if updated_field is not None and updated_field not in set_items:
            set_items[updated_field] = datetime.now(timezone.utc)

        # Recompute GSI key attributes affected by changed source attributes.
        known = {**key_attrs, **set_items}
        for key_def in cls.__keys__.values():
            if key_def.index is None:
                continue
            if not key_def.referenced_fields & set_items.keys():
                continue
            if not key_def.referenced_fields.issubset(known):
                missing = sorted(key_def.referenced_fields - known.keys())
                raise PydynanticError(
                    f"update() changes attribute(s) feeding index {key_def.name!r} but "
                    f"cannot recompute its key: also pass {missing} in set= so the index "
                    f"stays consistent."
                )
            set_items.update(key_def.key_attributes(known))

        add_items: dict[str, Any] = dict(add or {})
        if version_field is not None and version_field not in add_items:
            add_items[version_field] = 1

        # Optimistic-lock guard: refuse the write if the stored version moved
        # since the caller last read it.
        if expected_version is not None and version_field is not None:
            guard = F(version_field) == expected_version
            condition = guard if condition is None else (condition & guard)

        clauses: list[str] = []
        if set_items:
            parts = [f"{context.name(k)} = {context.value(v)}" for k, v in set_items.items()]
            clauses.append("SET " + ", ".join(parts))
        if remove:
            clauses.append("REMOVE " + ", ".join(context.name(k) for k in remove))
        if add_items:
            parts = [f"{context.name(k)} {context.value(v)}" for k, v in add_items.items()]
            clauses.append("ADD " + ", ".join(parts))
        if delete:
            parts = [f"{context.name(k)} {context.value(v)}" for k, v in delete.items()]
            clauses.append("DELETE " + ", ".join(parts))

        if not clauses:
            raise PydynanticError(
                "update() requires at least one write action; pass one of "
                "set=, remove=, add=, or delete=."
            )

        params: dict[str, Any] = {
            "TableName": cls._table_name(),
            "Key": cls.build_key(key_attrs),
            "UpdateExpression": " ".join(clauses),
            "ReturnValues": return_values,
        }
        if condition is not None:
            params["ConditionExpression"] = _compile_condition(condition, context)
        params["ExpressionAttributeNames"] = context.names
        if context.values:
            params["ExpressionAttributeValues"] = context.values

        try:
            response = cls._client().update_item(**params)
        except ClientError as exc:
            raise map_client_error(exc, versioned=version_field is not None) from exc

        attributes = response.get("Attributes")
        if not attributes:
            return None
        return cls.from_dynamo(attributes)

    # -- batch (delegates to the batch module) ------------------------------
    @classmethod
    def batch_get(
        cls,
        keys: list[Any],
        *,
        consistent: bool = False,
        attributes: list[str] | None = None,
    ) -> list[Self]:
        """Fetch many items by key, chunking and retrying transparently.

        ``attributes`` limits the response to a projection of attribute paths;
        omitted fields fall back to their model defaults (or fail validation if
        required), so include everything the entity needs to construct.
        """
        from .batch import batch_get

        return batch_get(cls, keys, consistent=consistent, attributes=attributes)

    @classmethod
    def batch_write(
        cls,
        *,
        puts: list[Self] | None = None,
        deletes: list[Any] | None = None,
    ) -> None:
        """Write/delete many items, chunking and retrying unprocessed items."""
        from .batch import batch_write

        batch_write(cls, puts=puts, deletes=deletes)

    # -- scan (delegates to the query module) -------------------------------
    @classmethod
    def scan(cls) -> ScanBuilder[Self]:
        """Return a builder for a full-table scan restricted to this entity.

        A scan reads the whole table; the builder automatically filters on the
        ``__entity__`` discriminator so only this entity's items are returned.
        Prefer :attr:`query` whenever a key condition applies.
        """
        from .query import ScanBuilder

        return ScanBuilder(cls)
