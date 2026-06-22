# Roadmap to 1.0

> **Status: shipped.** `pydynantic` reached **1.0.0** — every item below is done.
> This file is kept as the record of what 1.0 promised. New work lives in the
> issue tracker and `CHANGELOG.md`.

The road to **1.0 was about hardening, not net-new surface**: the single-table
feature set listed as *in scope for v1* in the README (entities, key composition,
CRUD, queries, filters, pagination, batch, transactions, collections and
optimistic locking) already existed. 1.0 locked down the public API, closed
correctness gaps, and shipped the docs and quality gates expected of a library
you'd pin in production.

`1.0` is a promise of **API stability** — now that it is tagged, the public
surface follows semver and breaking changes wait for `2.0`. Everything below
existed to make that promise safe to keep.

## Guiding principles

- **No raw `ClientError` leaks** — every failure maps into `PydynanticError`.
- **No silent data inconsistency** — when the library can't do the right thing
  (e.g. recompute a GSI key), it raises rather than writing a half-correct item.
- **Typed end to end** — `mypy --strict` clean, `py.typed` shipped, generics
  preserved through query/scan terminals.
- **Inject, don't own** — the boto3 client stays the caller's; no hidden global
  state, no implicit connections.
- **Synchronous only for 1.0** — async is explicitly a 2.0 concern.

---

## 0.3.0 — API completeness

Fill the obvious holes a user hits in week one.

- [x] **`ConsistentRead` on queries** — expose it on `QueryBuilder` (mirrors
      `get(consistent=...)`); GSIs reject it, so validate and raise early.
- [x] **Projection on `batch_get` and collections** — `ProjectionExpression`
      already exists on `get`/`query`/`scan`; extend it to the remaining reads.
- [x] **`ReturnValues` on `put`/`delete`** — return the previous item where the
      caller asks (e.g. `delete(..., return_values="ALL_OLD")`).
- [x] **TTL attribute support** — a `ttl_attr()` marker (like `version_attr()`)
      that serializes a `datetime`/`int` to the epoch-seconds attribute DynamoDB
      expects, so TTL-configured tables work without manual conversion.
- [x] **Auto-timestamps** — opt-in `created_at` / `updated_at` helpers that the
      ORM stamps on `put`/`update`.
- [x] **Collection pagination** — `CollectionQuery` currently drains every page;
      add `.limit()` / `.page(cursor=...)` parity with `QueryBuilder`.

## 0.4.0 — Correctness & edge cases

Harden the data path against the parts of DynamoDB that bite.

- [x] **Empty-string values** — DynamoDB now allows empty strings; decide and
      document whether they round-trip or are stripped (today `None`/empty sets
      are dropped in `serialize_item`).
- [x] **Typed set attributes** — verify `SS`/`NS`/`BS` round-trip for every
      supported element type and reject mixed-type sets with a clear error.
- [x] **Number precision** — pin the `Decimal` context to DynamoDB's 38-digit /
      ±10^125 limits and raise a friendly error on overflow instead of a boto3
      one.
- [x] **Cursor robustness** — document the pagination cursor's opacity contract;
      decide whether to sign/version it so a tampered or stale cursor fails
      loudly rather than mis-paginating.
- [x] **`one_or_none()` with an explicit `.limit(1)`** — today a user-set limit
      can mask a genuine "multiple results" case; make the contract explicit
      (raise, or document the override).
- [x] **Reserved-word / dotted-path fuzzing** — property-test the expression
      builder so no attribute name can collide or break `ExpressionAttributeNames`.

## 0.5.0 — Quality gates

Make "it works" provable and keep it that way.

- [x] **Coverage to ~100%** — close the remaining branches in `batch.py`
      (backoff/retry), `entity.py`, `keys.py`, `table.py`. _(now 99%)_
- [x] **Integration parity** — the CI integration job (DynamoDB Local) should
      exercise the same matrix the moto unit tests do, not just a smoke test.
- [x] **Property-based tests** — `hypothesis` for marshalling round-trips and
      key template render/parse symmetry.
- [x] **Benchmarks** — a small, tracked suite (marshalling throughput, query
      pagination overhead) to catch regressions before they ship.
- [x] **Tooling** — `pre-commit` config, Dependabot, Codecov (or coverage gate
      bump), and an automated **GitHub Release** step in the release workflow
      (today it publishes to PyPI but does not create the GH release).

## 0.6.0 — Documentation & DX

What turns a working library into one people adopt.

- [x] **Docs site** — MkDocs (Material) with: single-table-design primer, full
      API reference (mkdocstrings), and a recipe/cookbook section.
- [x] **Migration guides** — "coming from ElectroDB / DynamoDB-Toolbox" mapping
      tables; the README already pitches against them, so close the loop.
- [x] **Worked examples** — a runnable example app (e.g. multi-tenant SaaS data
      model) in `examples/`.
- [x] **Error-message audit** — every raised `PydynanticError` should tell the
      user what to do next (the new stale-GSI error is the template).
- [x] **Observability hooks** — optional callback/logging around each DynamoDB
      call for tracing and cost attribution, without forcing a logging dep.

## 1.0.0 — Stabilize

The release itself is mostly process, not code.

- [x] **API freeze & review** — audit every public symbol in `__all__`; mark
      anything still uncertain as provisional or drop it before the freeze.
- [x] **Deprecation policy** — document the support window and how breaking
      changes will be staged (`DeprecationWarning` → removal in next major).
- [x] **`Development Status :: 5 - Production/Stable`** classifier in
      `pyproject.toml` (currently `3 - Alpha`).
- [x] **Tag-naming consistency** — standardize on `vX.Y.Z` or bare `X.Y.Z` for
      release tags (0.1.0 used `v0.1.0`, 0.2.0 used `0.2.0`).
- [x] **CHANGELOG + upgrade notes** for 1.0; announce.

---

## Definition of done for 1.0

1. Public API frozen, documented, and reviewed; semver commitment in effect.
2. `mypy --strict` and `ruff` clean; coverage ≥ 98% with integration parity.
3. Full docs site live (concepts + API reference + recipes + migration guides).
4. No known correctness gaps in the marshalling or key/expression paths.
5. Release automation produces both the PyPI artifact and the GitHub Release.

## Explicitly deferred to 2.0 (non-goals for 1.0)

- **Async** support on `aioboto3`.
- **Table / infrastructure provisioning** (use CDK/Terraform).
- **Data migrations** and schema-evolution tooling.
- **Multi-table joins** / cross-table query planning.

These are valuable but out of scope; keeping them out is what makes a focused,
trustworthy 1.0 reachable.
