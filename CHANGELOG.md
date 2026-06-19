# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-19

First public release.

### Added
- **Declarative entities** on top of Pydantic v2 with single-table metadata
  (entity discriminator, key templates, table binding).
- **Key composition**: build and parse `{placeholder}` templates for the
  primary key and GSIs, with validation of referenced attributes at class
  definition time.
- **Marshalling** between Python and DynamoDB for `str`, `int`, `float`,
  `Decimal`, `bool`, `bytes`, `datetime`, `date`, `UUID`, `Enum`, `list`,
  `dict`, `set`, and nested Pydantic models (numbers stored as `Decimal`).
- **CRUD**: `put`, `get`, `get_or_raise`, `update`, `delete` with condition
  expressions; automatic `UpdateExpression` generation and recomputation of
  GSI keys whose source attributes change.
- **Typed query builder** with named access patterns, all sort-key operators
  (`eq`, `begins_with`, `between`, `gt`, `gte`, `lt`, `lte`) and terminals
  (`all`, `one`, `one_or_none`, `first`, `iter`, `page`).
- **Filter / condition DSL** via `F(...)` with managed, collision-free
  `ExpressionAttributeNames`/`Values` and `&` / `|` / `~` composition.
- **Opaque cursor pagination** (`Page`, `encode_cursor`, `decode_cursor`).
- **Batch** get/write with 25/100 chunking and retry of unprocessed
  items/keys with backoff.
- **Transactions** mapped to `TransactWriteItems` with atomic rollback on a
  failed condition (`put`, `update`, `delete`, `condition_check`).
- **Collections**: retrieve several entity types from one partition.
- **Optimistic locking** via `version_attr()` raising `OptimisticLockError`.
- Dedicated exception hierarchy rooted at `PydynanticError`.
- `py.typed` marker; `mypy --strict` clean; CI matrix for Python 3.10–3.13.

[Unreleased]: https://github.com/robertruben98/pydynantic/compare/0.1.0...HEAD
[0.1.0]: https://github.com/robertruben98/pydynantic/releases/tag/0.1.0
