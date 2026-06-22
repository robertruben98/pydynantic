"""Tests for auto-managed created_at / updated_at timestamp attributes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pydynantic import Entity, key
from pydynantic.attributes import created_at_attr
from pydynantic.errors import ConditionCheckFailedError
from pydynantic.expressions import attr_exists


def test_put_sets_both_stamps(models: object) -> None:
    Stamped = models.Stamped  # type: ignore[attr-defined]
    item = Stamped(stamp_id="s1", org_id="o1")
    assert item.created_at is None and item.updated_at is None
    Stamped.put(item)
    assert item.created_at is not None
    assert item.updated_at is not None


def test_reput_preserves_created_advances_updated(models: object) -> None:
    Stamped = models.Stamped  # type: ignore[attr-defined]
    item = Stamped(stamp_id="s1", org_id="o1")
    Stamped.put(item)
    created_before = item.created_at
    updated_before = item.updated_at
    assert created_before is not None and updated_before is not None

    Stamped.put(item)
    assert item.created_at == created_before
    assert item.updated_at is not None and item.updated_at >= updated_before


def test_update_advances_updated_leaves_created(models: object) -> None:
    Stamped = models.Stamped  # type: ignore[attr-defined]
    item = Stamped(stamp_id="s1", org_id="o1")
    Stamped.put(item)
    created = item.created_at
    updated_before = item.updated_at
    assert created is not None and updated_before is not None

    # No explicit action needed: the auto-stamp of updated_at is itself a write.
    Stamped.update(org_id="o1", stamp_id="s1")

    fetched = Stamped.get(org_id="o1", stamp_id="s1")
    assert fetched is not None
    assert fetched.created_at == created
    assert fetched.updated_at is not None and fetched.updated_at >= updated_before


def test_update_explicit_updated_at_wins(models: object) -> None:
    Stamped = models.Stamped  # type: ignore[attr-defined]
    item = Stamped(stamp_id="s1", org_id="o1")
    Stamped.put(item)

    fixed = datetime(2020, 1, 1, tzinfo=timezone.utc)
    Stamped.update(org_id="o1", stamp_id="s1", set={"updated_at": fixed})

    fetched = Stamped.get(org_id="o1", stamp_id="s1")
    assert fetched is not None
    assert fetched.updated_at == fixed


def test_failed_put_rolls_back_stamps(models: object) -> None:
    Stamped = models.Stamped  # type: ignore[attr-defined]
    item = Stamped(stamp_id="s1", org_id="o1")
    # Require the item to already exist; it does not, so the write fails.
    with pytest.raises(ConditionCheckFailedError):
        Stamped.put(item, condition=attr_exists("PK"))
    assert item.created_at is None
    assert item.updated_at is None


def test_duplicate_created_at_raises(models: object) -> None:
    table = models.table  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="more than one created_at field declared"):

        class Bad(Entity, table=table, name="bad_created"):
            bad_id: str
            first: datetime | None = created_at_attr()
            second: datetime | None = created_at_attr()

            class Meta:
                primary = key(pk="BAD#{bad_id}", sk="BAD#{bad_id}")
