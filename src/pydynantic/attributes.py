"""Special attribute markers (e.g. optimistic-locking version fields)."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo

#: Marker key placed in ``json_schema_extra`` to flag a version attribute.
VERSION_MARKER = "__pydynantic_version__"


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
