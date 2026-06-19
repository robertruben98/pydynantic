"""Exception hierarchy for pydynantic.

All errors raised by the library derive from :class:`PydynanticError` so that
callers never have to catch raw ``botocore.exceptions.ClientError``.
"""

from __future__ import annotations

from typing import Any


class PydynanticError(Exception):
    """Base class for every error raised by pydynantic."""


class ItemNotFoundError(PydynanticError):
    """Raised when a required item does not exist (e.g. ``get``/``one``)."""


class ConditionCheckFailedError(PydynanticError):
    """Raised when a write fails because its condition expression was not met."""


class OptimisticLockError(ConditionCheckFailedError):
    """Raised when a versioned write loses an optimistic-locking race."""


class ValidationError(PydynanticError):
    """Wraps a :class:`pydantic.ValidationError` for schema violations."""


class KeyTemplateError(PydynanticError):
    """Raised when a key template references an attribute that is missing."""


class TransactionCanceledError(PydynanticError):
    """Raised when a ``TransactWriteItems`` call is cancelled.

    The per-action cancellation ``reasons`` (as returned by DynamoDB) are
    exposed on the ``reasons`` attribute for diagnostics.
    """

    def __init__(self, message: str, reasons: list[Any] | None = None) -> None:
        super().__init__(message)
        self.reasons: list[Any] = list(reasons or [])


class MultipleResultsError(PydynanticError):
    """Raised by ``one``/``one_or_none`` when more than one item matches."""
