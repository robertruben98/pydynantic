"""Benchmark the marshalling layer: ``to_dynamo()`` / ``from_dynamo()``.

Measures pure (de)serialization throughput on a representative entity with a
mix of str/int/Decimal/datetime/list/dict/set attributes -- no network/DynamoDB
calls involved, so this isolates the marshalling cost.
"""

from __future__ import annotations

from types import SimpleNamespace

from conftest import sample_record


def test_to_dynamo(benchmark: object, models: SimpleNamespace) -> None:
    record = sample_record(models, 1)
    item = benchmark(record.to_dynamo)  # type: ignore[operator]
    assert "PK" in item


def test_from_dynamo(benchmark: object, models: SimpleNamespace) -> None:
    record = sample_record(models, 1)
    item = record.to_dynamo()
    Record = models.Record
    result = benchmark(Record.from_dynamo, item)  # type: ignore[operator]
    assert result.record_id == "r1"


def test_round_trip(benchmark: object, models: SimpleNamespace) -> None:
    record = sample_record(models, 1)
    Record = models.Record

    def round_trip() -> object:
        return Record.from_dynamo(record.to_dynamo())

    result = benchmark(round_trip)  # type: ignore[operator]
    assert result.record_id == "r1"
