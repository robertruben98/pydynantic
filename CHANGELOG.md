# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `QueryBuilder.consistent(value=True)` — request a strongly consistent read
  (`ConsistentRead`); mirrors `get(consistent=...)` and rejects use on a GSI.
- `attributes=` projection on `Entity.batch_get` and `Collection.query` —
  limit reads to a `ProjectionExpression` (projected-away fields fall back to
  model defaults); collections auto-include the `__entity__` discriminator.
- `return_values=` on `Entity.put` and `Entity.delete` (`NONE` | `ALL_OLD`) —
  `delete(..., return_values="ALL_OLD")` returns the deleted item (or `None`);
  `put` still always returns the written item.
- Collection pagination — fluent `CollectionQuery.limit()` / `.page(cursor=...)`
  returning a `CollectionPage` (bucketed result + opaque cursor + `has_more`);
  `.all()` still drains every page.
- `ttl_attr()` — mark a `datetime`/`int` field as a DynamoDB TTL attribute;
  it is stored as a Unix-epoch-seconds Number and round-trips back to the
  declared type (no manual conversion).
- `created_at_attr()` / `updated_at_attr()` — opt-in auto-timestamps; `put`
  stamps `created_at` once and `updated_at` every write, `update` refreshes
  `updated_at` (unless set explicitly), with in-memory rollback on a failed put.

### Changed
- Release workflow now also creates a GitHub Release (notes sliced from this
  changelog) on tag pushes, in addition to publishing to PyPI.
- Added a `pre-commit` config (ruff lint + format, hygiene hooks) and Dependabot
  (weekly `github-actions` + `pip` updates).

## [0.2.0] - 2026-06-20

### Added
- `Entity.scan()` — full-table scan restricted to the entity via its
  `__entity__` discriminator, with `filter`, `limit`, `attributes`, `all`,
  `first`, `iter`, `page` and `count` (exported as `ScanBuilder`).
- `QueryBuilder.count()` / `ScanBuilder.count()` — server-side `Select=COUNT`.
- `QueryBuilder.attributes([...])` and `get(attributes=[...])` —
  `ProjectionExpression` support to fetch only selected attributes.
- CI job running the integration suite against `amazon/dynamodb-local`.

### Fixed
- `put()` on a versioned entity no longer leaves the in-memory `version`
  incremented when the conditional write fails, so a retry after re-reading
  works correctly.
- `update()` now raises instead of silently leaving a GSI key stale when it
  changes an attribute feeding that index but cannot recompute the full key
  (missing source attributes); the error names the missing attributes.
- `batch_get()` deduplicates keys before issuing the request, avoiding the
  `ValidationException` DynamoDB raises for duplicate keys.

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

[Unreleased]: https://github.com/robertruben98/pydynantic/compare/0.2.0...HEAD
[0.2.0]: https://github.com/robertruben98/pydynantic/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/robertruben98/pydynantic/releases/tag/0.1.0
