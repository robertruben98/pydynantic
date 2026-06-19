"""Key templates: composition (build) and parsing (reverse) of DynamoDB keys.

A key template is a string with ``{placeholder}`` fields that reference entity
attributes, for example ``"ORG#{org_id}"``. Templates support literal
prefixes/suffixes and multiple placeholders in a single key.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from .errors import KeyTemplateError

if TYPE_CHECKING:
    from .table import Table

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def template_fields(template: str) -> list[str]:
    """Return the attribute names referenced by a template, in order."""
    return _PLACEHOLDER.findall(template)


def _key_str(value: Any) -> str:
    """Render a single attribute value as a key component string."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Enum):
        return _key_str(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def render(template: str, attrs: dict[str, Any]) -> str:
    """Resolve ``template`` against ``attrs``, substituting every placeholder.

    Raises :class:`KeyTemplateError` if a referenced attribute is missing or
    ``None``.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in attrs or attrs[name] is None:
            raise KeyTemplateError(
                f"Cannot build key {template!r}: missing value for attribute {name!r}"
            )
        return _key_str(attrs[name])

    return _PLACEHOLDER.sub(_replace, template)


def parse(template: str, value: str) -> dict[str, str]:
    """Extract placeholder values from a composed key string (reverse of render).

    This is primarily a debugging / introspection aid. It works when the
    template has unambiguous literal separators between placeholders.
    """
    pattern = "^"
    last = 0
    for match in _PLACEHOLDER.finditer(template):
        pattern += re.escape(template[last : match.start()])
        pattern += f"(?P<{match.group(1)}>.+?)"
        last = match.end()
    pattern += re.escape(template[last:]) + "$"

    matched = re.match(pattern, value)
    if matched is None:
        raise KeyTemplateError(f"Value {value!r} does not match template {template!r}")
    return matched.groupdict()


class KeyDefinition:
    """A primary or secondary-index key declared on an entity's ``Meta``.

    Instances are created by the :func:`key` factory and bound to a concrete
    :class:`~pydynantic.table.Table` (which resolves the physical attribute
    names) when the owning entity class is created.
    """

    def __init__(
        self,
        *,
        pk: str,
        sk: str | None = None,
        index: str | None = None,
    ) -> None:
        self.pk_template = pk
        self.sk_template = sk
        self.index = index
        # Populated by ``bind`` once the owning entity (and its table) is known.
        self.name: str = ""
        self.pk_attr: str = ""
        self.sk_attr: str | None = None

    @property
    def referenced_fields(self) -> set[str]:
        """All entity attributes this key reads, across its pk and sk templates."""
        fields = set(template_fields(self.pk_template))
        if self.sk_template is not None:
            fields.update(template_fields(self.sk_template))
        return fields

    def bind(self, name: str, table: Table) -> None:
        """Resolve physical attribute names against the table configuration."""
        self.name = name
        if self.index is None:
            self.pk_attr = table.pk
            self.sk_attr = table.sk
        else:
            if self.index not in table.indexes:
                raise KeyTemplateError(
                    f"Key {name!r} references unknown index {self.index!r}"
                )
            index = table.indexes[self.index]
            self.pk_attr = index.pk
            self.sk_attr = index.sk
        if self.sk_template is not None and self.sk_attr is None:
            raise KeyTemplateError(
                f"Key {name!r} defines a sort key but its index has no sort key"
            )

    def build_pk(self, attrs: dict[str, Any]) -> str:
        """Render the partition-key string from the given attribute values."""
        return render(self.pk_template, attrs)

    def build_sk(self, attrs: dict[str, Any]) -> str | None:
        """Render the sort-key string, or ``None`` if this key has no sort key."""
        if self.sk_template is None:
            return None
        return render(self.sk_template, attrs)

    def key_attributes(self, attrs: dict[str, Any]) -> dict[str, str]:
        """Return the physical key attributes (pk/sk) for an item.

        Returns an empty mapping if the required attributes for this key are not
        all present, which lets non-projected entities skip optional GSIs.
        """
        if not self.referenced_fields.issubset(attrs):
            return {}
        result = {self.pk_attr: self.build_pk(attrs)}
        sk_value = self.build_sk(attrs)
        if sk_value is not None and self.sk_attr is not None:
            result[self.sk_attr] = sk_value
        return result


def key(*, pk: str, sk: str | None = None, index: str | None = None) -> KeyDefinition:
    """Declare a key template for an entity.

    :param pk: partition-key template, e.g. ``"ORG#{org_id}"``.
    :param sk: optional sort-key template, e.g. ``"USER#{user_id}"``.
    :param index: GSI name (from the table's ``indexes``); ``None`` = primary.
    """
    return KeyDefinition(pk=pk, sk=sk, index=index)
