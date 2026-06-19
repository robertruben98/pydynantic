"""Fluent condition / filter expression DSL.

``F("status") == "active"`` builds a :class:`Condition` that compiles to a
DynamoDB expression string with managed ``ExpressionAttributeNames`` and
``ExpressionAttributeValues`` (no placeholder collisions).

Conditions combine with ``&`` (AND), ``|`` (OR) and ``~`` (NOT).
"""

from __future__ import annotations

from typing import Any

from .marshalling import AttributeValue, serialize


class ExpressionContext:
    """Allocates collision-free ``#name`` / ``:value`` placeholders."""

    def __init__(self) -> None:
        self.names: dict[str, str] = {}
        self.values: dict[str, AttributeValue] = {}
        self._name_for_attr: dict[str, str] = {}
        self._name_count = 0
        self._value_count = 0

    def name(self, attribute: str) -> str:
        """Register an attribute path (dotted segments allowed) and return its alias."""
        parts = attribute.split(".")
        rendered: list[str] = []
        for part in parts:
            if part not in self._name_for_attr:
                placeholder = f"#n{self._name_count}"
                self._name_count += 1
                self._name_for_attr[part] = placeholder
                self.names[placeholder] = part
            rendered.append(self._name_for_attr[part])
        return ".".join(rendered)

    def value(self, value: Any) -> str:
        """Register a value (serialized to an AttributeValue) and return its alias."""
        placeholder = f":v{self._value_count}"
        self._value_count += 1
        self.values[placeholder] = serialize(value)
        return placeholder


class Condition:
    """Base class for all expression nodes. Combine with ``&``, ``|``, ``~``."""

    def compile(self, context: ExpressionContext) -> str:  # pragma: no cover
        raise NotImplementedError

    def __and__(self, other: Condition) -> Condition:
        return _BoolOp("AND", self, other)

    def __or__(self, other: Condition) -> Condition:
        return _BoolOp("OR", self, other)

    def __invert__(self) -> Condition:
        return _Not(self)


class _Comparison(Condition):
    def __init__(self, path: str, operator: str, value: Any) -> None:
        self.path = path
        self.operator = operator
        self.value = value

    def compile(self, context: ExpressionContext) -> str:
        return f"{context.name(self.path)} {self.operator} {context.value(self.value)}"


class _Between(Condition):
    def __init__(self, path: str, low: Any, high: Any) -> None:
        self.path = path
        self.low = low
        self.high = high

    def compile(self, context: ExpressionContext) -> str:
        name = context.name(self.path)
        return f"{name} BETWEEN {context.value(self.low)} AND {context.value(self.high)}"


class _Function(Condition):
    def __init__(self, func: str, path: str, value: Any | None = None) -> None:
        self.func = func
        self.path = path
        self.value = value
        self.has_value = value is not None

    def compile(self, context: ExpressionContext) -> str:
        name = context.name(self.path)
        if self.has_value:
            return f"{self.func}({name}, {context.value(self.value)})"
        return f"{self.func}({name})"


class _In(Condition):
    def __init__(self, path: str, values: list[Any]) -> None:
        if not values:
            raise ValueError("is_in() requires at least one value")
        self.path = path
        self.values = values

    def compile(self, context: ExpressionContext) -> str:
        name = context.name(self.path)
        placeholders = ", ".join(context.value(value) for value in self.values)
        return f"{name} IN ({placeholders})"


class _AttributeType(Condition):
    def __init__(self, path: str, type_code: str) -> None:
        self.path = path
        self.type_code = type_code

    def compile(self, context: ExpressionContext) -> str:
        return f"attribute_type({context.name(self.path)}, {context.value(self.type_code)})"


class _BoolOp(Condition):
    def __init__(self, operator: str, left: Condition, right: Condition) -> None:
        self.operator = operator
        self.left = left
        self.right = right

    def compile(self, context: ExpressionContext) -> str:
        return f"({self.left.compile(context)} {self.operator} {self.right.compile(context)})"


class _Not(Condition):
    def __init__(self, inner: Condition) -> None:
        self.inner = inner

    def compile(self, context: ExpressionContext) -> str:
        return f"(NOT {self.inner.compile(context)})"


class F:
    """Reference to an attribute, used to build :class:`Condition` objects.

    Supports dotted paths for nested map attributes, e.g. ``F("address.city")``.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def __eq__(self, value: object) -> Condition:  # type: ignore[override]
        return _Comparison(self.path, "=", value)

    def __ne__(self, value: object) -> Condition:  # type: ignore[override]
        return _Comparison(self.path, "<>", value)

    def __lt__(self, value: Any) -> Condition:
        return _Comparison(self.path, "<", value)

    def __le__(self, value: Any) -> Condition:
        return _Comparison(self.path, "<=", value)

    def __gt__(self, value: Any) -> Condition:
        return _Comparison(self.path, ">", value)

    def __ge__(self, value: Any) -> Condition:
        return _Comparison(self.path, ">=", value)

    def between(self, low: Any, high: Any) -> Condition:
        return _Between(self.path, low, high)

    def begins_with(self, prefix: str) -> Condition:
        return _Function("begins_with", self.path, prefix)

    def contains(self, value: Any) -> Condition:
        return _Function("contains", self.path, value)

    def exists(self) -> Condition:
        return _Function("attribute_exists", self.path)

    def not_exists(self) -> Condition:
        return _Function("attribute_not_exists", self.path)

    def is_in(self, values: list[Any]) -> Condition:
        return _In(self.path, values)

    def is_type(self, type_code: str) -> Condition:
        return _AttributeType(self.path, type_code)

    # ``F`` defines ``__eq__`` so it is unhashable by default; restore hashing
    # so attribute references can live in sets / dict keys if needed.
    __hash__ = object.__hash__


def attr_exists(path: str) -> Condition:
    """Convenience: ``attribute_exists(path)``."""
    return F(path).exists()


def attr_not_exists(path: str) -> Condition:
    """Convenience: ``attribute_not_exists(path)`` (e.g. create-only puts)."""
    return F(path).not_exists()


def compile_condition(
    condition: Condition, context: ExpressionContext | None = None
) -> tuple[str, ExpressionContext]:
    """Compile a condition into ``(expression, context)``."""
    context = context or ExpressionContext()
    return condition.compile(context), context
