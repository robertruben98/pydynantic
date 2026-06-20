"""Benchmark query pagination overhead against a moto-mocked table.

Seeds N items into a single partition, then measures two access patterns:

* ``.all()`` -- drains every page transparently (full materialisation cost).
* ``.page()`` -- a single bounded page plus cursor encoding (pagination
  overhead in isolation).

These hit moto (in-process), so absolute numbers are dominated by moto rather
than DynamoDB, but they make query/marshalling regressions on the hot path
catchable.
"""

from __future__ import annotations

from types import SimpleNamespace

from conftest import sample_record

N = 200


def _seed(models: SimpleNamespace, n: int = N) -> None:
    Record = models.Record
    for i in range(n):
        Record.put(sample_record(models, i))


def test_query_all(benchmark: object, models: SimpleNamespace) -> None:
    _seed(models)
    Record = models.Record

    def drain() -> list[object]:
        return Record.query.primary(org_id="acme").all()

    results = benchmark(drain)  # type: ignore[operator]
    assert len(results) == N


def test_query_page(benchmark: object, models: SimpleNamespace) -> None:
    _seed(models)
    Record = models.Record

    def one_page() -> object:
        return Record.query.primary(org_id="acme").limit(50).page()

    page = benchmark(one_page)  # type: ignore[operator]
    assert len(page.items) == 50
    assert page.cursor is not None
