"""pydynantic: single-table design for DynamoDB, with typed Pydantic entities."""

from __future__ import annotations

from pydantic import Field

from .attributes import version_attr
from .collections import Collection, CollectionResult
from .entity import Entity
from .errors import (
    ConditionCheckFailedError,
    ItemNotFoundError,
    KeyTemplateError,
    MultipleResultsError,
    OptimisticLockError,
    PydynanticError,
    TransactionCanceledError,
    ValidationError,
)
from .expressions import Condition, F, attr_exists, attr_not_exists
from .keys import KeyDefinition, key
from .pagination import Page, decode_cursor, encode_cursor
from .query import QueryBuilder, QueryNamespace, ScanBuilder
from .table import Index, Table
from .transactions import Transaction, transaction

__version__ = "0.1.0"

__all__ = [
    # Core
    "Table",
    "Index",
    "Entity",
    "key",
    "KeyDefinition",
    "version_attr",
    "Field",
    # Expressions
    "F",
    "Condition",
    "attr_exists",
    "attr_not_exists",
    # Query / pagination
    "QueryBuilder",
    "QueryNamespace",
    "ScanBuilder",
    "Page",
    "encode_cursor",
    "decode_cursor",
    # Collections
    "Collection",
    "CollectionResult",
    # Transactions
    "transaction",
    "Transaction",
    # Errors
    "PydynanticError",
    "ItemNotFoundError",
    "ConditionCheckFailedError",
    "OptimisticLockError",
    "ValidationError",
    "TransactionCanceledError",
    "KeyTemplateError",
    "MultipleResultsError",
]
