# Benchmarks

A small, manually-run performance suite for `pydynantic`. It tracks two hot
paths so regressions are catchable:

- **Marshalling throughput** (`test_marshalling_bench.py`) — `to_dynamo()` /
  `from_dynamo()` and the full round-trip on a representative entity mixing
  `str`/`int`/`Decimal`/`datetime`/`list`/`dict`/`set`. No DynamoDB involved,
  so this isolates the (de)serialization cost.
- **Query pagination overhead** (`test_query_bench.py`) — seeds N items (200)
  into a [`moto`](https://github.com/getmoto/moto)-mocked table, then measures
  draining a full `query.primary(...).all()` versus a single bounded `.page()`
  call. Numbers are dominated by in-process `moto`, not real DynamoDB, but they
  surface regressions on the query/marshalling path.

## Running

Install the dev extras (which now include `pytest-benchmark`):

```bash
pip install -e ".[dev]"
```

Then run only the benchmarks:

```bash
pytest benchmarks/ --benchmark-only
```

Useful extras:

```bash
# Save a baseline and compare later runs against it
pytest benchmarks/ --benchmark-only --benchmark-save=baseline
pytest benchmarks/ --benchmark-only --benchmark-compare=baseline
```

## Not part of the CI gate

These benchmarks are **not** wired into CI and are **not** collected by the
normal test run. The project's `pyproject.toml` sets
`[tool.pytest.ini_options] testpaths = ["tests"]`, so a bare `pytest` only
picks up `tests/` — `benchmarks/` is ignored unless you point pytest at it
explicitly (`pytest benchmarks/`). Run them manually / locally when you want to
check perf.
