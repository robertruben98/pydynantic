"""Special attribute markers (e.g. optimistic-locking version fields)."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo

#: Marker key placed in ``json_schema_extra`` to flag a version attribute.
VERSION_MARKER = "__pydynantic_version__"

#: Marker key placed in ``json_schema_extra`` to flag a TTL attribute.
TTL_MARKER = "__pydynantic_ttl__"

#: Marker key placed in ``json_schema_extra`` to flag a created-at attribute.
CREATED_AT_MARKER = "__pydynantic_created_at__"

#: Marker key placed in ``json_schema_extra`` to flag an updated-at attribute.
UPDATED_AT_MARKER = "__pydynantic_updated_at__"


def version_attr(default: int = 0, **kwargs: Any) -> Any:
    """Mark an integer field as the optimistic-locking version attribute.

    On every versioned ``put``, the version is incremented and a condition is
    added requiring the stored version to match; a lost race raises
    :class:`~pydynantic.errors.OptimisticLockError`.
    """
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra[VERSION_MARKER] = True
    return Field(default=default, json_schema_extra=extra, **kwargs)


def is_version_field(field: FieldInfo) -> bool:
    """Return ``True`` if a Pydantic field was declared via :func:`version_attr`."""
    extra = field.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get(VERSION_MARKER))


def ttl_attr(default: Any = None, **kwargs: Any) -> Any:
    """Mark a field as the DynamoDB Time-To-Live (TTL) attribute.

    DynamoDB requires the TTL attribute to be a Number holding a Unix epoch
    timestamp in seconds. The field may be declared as a ``datetime | None`` (the
    common case) or an ``int``; on every ``put`` the stored value is overridden to
    an epoch-seconds Number regardless of the model's default ISO datetime
    encoding. Reading back coerces the epoch into a ``datetime`` (UTC), so
    sub-second precision is dropped.

    The default is ``None`` (TTL is optional). When the value is ``None`` the
    attribute is omitted from the stored item entirely.

    Timezone: TTL ``datetime`` values should be timezone-aware. Naive datetimes
    are passed to ``.timestamp()`` unchanged (interpreted in the local timezone by
    Python); pydynantic does not reinterpret them, so prefer tz-aware values.
    """
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra[TTL_MARKER] = True
    return Field(default=default, json_schema_extra=extra, **kwargs)


def is_ttl_field(field: FieldInfo) -> bool:
    """Return ``True`` if a Pydantic field was declared via :func:`ttl_attr`."""
    extra = field.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get(TTL_MARKER))


def created_at_attr(**kwargs: Any) -> Any:
    """Mark a ``datetime | None`` field as the auto-managed creation timestamp.

    On the first ``put`` (when the field is still ``None``) pydynantic stamps the
    field with ``datetime.now(timezone.utc)``. Subsequent puts leave it untouched,
    and ``update`` never modifies it.
    """
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra[CREATED_AT_MARKER] = True
    return Field(default=None, json_schema_extra=extra, **kwargs)


def is_created_at_field(field: FieldInfo) -> bool:
    """Return ``True`` if a Pydantic field was declared via :func:`created_at_attr`."""
    extra = field.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get(CREATED_AT_MARKER))


def updated_at_attr(**kwargs: Any) -> Any:
    """Mark a ``datetime | None`` field as the auto-managed modification timestamp.

    On every ``put`` the field is stamped with ``datetime.now(timezone.utc)``. On
    ``update`` it is stamped too, unless the caller explicitly supplies it in
    ``set=`` (in which case the caller's value wins).
    """
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra[UPDATED_AT_MARKER] = True
    return Field(default=None, json_schema_extra=extra, **kwargs)


def is_updated_at_field(field: FieldInfo) -> bool:
    """Return ``True`` if a Pydantic field was declared via :func:`updated_at_attr`."""
    extra = field.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get(UPDATED_AT_MARKER))
