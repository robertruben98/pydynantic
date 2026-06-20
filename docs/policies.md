# Project policies

This page documents the stability, deprecation, Python-support, and release-tag
commitments that `pydynantic` makes from **1.0.0** onward. The goal is predictability:
you should be able to pin a major version and upgrade minors/patches without surprises.

## Semantic versioning

`pydynantic` follows [Semantic Versioning 2.0.0](https://semver.org/) once 1.0.0 ships.
Versions are `MAJOR.MINOR.PATCH`:

- **MAJOR** — incompatible (breaking) changes to the public API.
- **MINOR** — new, backwards-compatible functionality (including new deprecations).
- **PATCH** — backwards-compatible bug fixes.

### What "the public API" means

The public API is **everything exported from the top-level `pydynantic` package** —
that is, every name in [`pydynantic.__all__`](reference/api.md). This includes classes
you instantiate (`Table`, `Entity`, `Transaction`), factory functions (`key`,
`transaction`, `encode_cursor`/`decode_cursor`), expression helpers (`F`,
`attr_exists`, `attr_not_exists`), the attribute helpers (`version_attr`, `ttl_attr`,
`created_at_attr`, `updated_at_attr`), the re-exported `Field`, and the exception
hierarchy rooted at `PydynanticError`.

Builder and definition types such as `QueryBuilder`, `ScanBuilder`, `QueryNamespace`,
`KeyDefinition`, `Condition`, and `OperationHook` are part of the public surface too:
they are the **return and parameter types** of public methods (e.g. `Entity.scan()`
returns a `ScanBuilder`, `key()` returns a `KeyDefinition`, `F(...)` builds a
`Condition`). They are intended to be referenced in type annotations and isinstance
checks, and are covered by the same stability guarantee.

**Not** part of the public API, and changeable at any time without a major bump:

- Any name prefixed with an underscore (`_Comparison`, `_ClientProxy`, …).
- Any module not re-exported from the top-level package (importing from
  `pydynantic.query`, `pydynantic.expressions`, etc. is unsupported).
- The string value of `__version__` as a parseable contract beyond SemVer ordering.
- Behaviour explicitly documented as "internal", "experimental", or "subject to change".

We commit to introducing breaking changes to the public API **only in a new major
release**.

## Deprecation process

Nothing in the public API is removed or changed incompatibly without a deprecation
period. The process for retiring a symbol, parameter, or behaviour is:

1. **Announce in a minor release.** The deprecated symbol/parameter keeps working and
   emits a `DeprecationWarning` (via `warnings.warn(..., DeprecationWarning,
   stacklevel=2)`) the first time it is used. The warning message names the
   replacement and the earliest version in which removal may occur.
2. **Document it.** The deprecation is recorded in the
   [CHANGELOG](https://github.com/robertruben98/pydynantic/blob/main/CHANGELOG.md)
   under a **Deprecated** heading for that release, and the symbol's docstring is
   annotated (e.g. with a `.. deprecated::` / "Deprecated since" note).
3. **Honour a minimum grace period.** A deprecated API remains available, with its
   warning, for **at least one full minor release** before it becomes eligible for
   removal.
4. **Remove only in the next major.** Actual removal of a deprecated public API happens
   in the next **major** version, never in a minor or patch. The removal is listed in
   the CHANGELOG under a **Removed** heading.

This gives downstream code a clear, machine-detectable upgrade path: run your test suite
with `-W error::DeprecationWarning` to surface anything that will break in the next major.

## Supported Python versions

`pydynantic` supports the CPython versions exercised in CI:

| Status     | Versions                       |
| ---------- | ------------------------------ |
| Supported  | 3.10, 3.11, 3.12, 3.13         |

Policy for changing this set:

- **Adding** a newly released Python version is a backwards-compatible change and may
  land in a **minor** release once it is green in CI.
- **Dropping** a Python version (typically once it reaches
  [end-of-life](https://devguide.python.org/versions/)) is a breaking change and is done
  only in a **major** release. The drop is announced in the CHANGELOG under
  **Deprecated**/**Removed** and the `requires-python` constraint is updated accordingly.

## Release-tag naming

Releases are cut from Git tags. The standard, going forward, is a **bare** version tag:

```
X.Y.Z          e.g.  1.0.0, 1.2.3
```

Bare tags are the primary trigger of the release workflow that publishes to PyPI.

!!! note "Historical exception"
    The `0.1.0` release was tagged `v0.1.0` (with a leading `v`). That tag is preserved
    for history, but **all releases from now on use bare `X.Y.Z` tags** to match the
    release workflow. Do not create `v`-prefixed tags.
