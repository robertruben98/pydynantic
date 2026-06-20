"""Tests for the query builder: sort-key operators, filters, terminals, GSIs."""

from __future__ import annotations

import pytest

from pydynantic import F
from pydynantic.errors import ItemNotFoundError, MultipleResultsError


def seed(models: object, n: int = 5) -> None:
    User = models.User  # type: ignore[attr-defined]
    for i in range(1, n + 1):
        User.put(
            User(
                user_id=f"u{i}",
                org_id="acme",
                email=f"u{i}@x.com",
                name=f"User {i}",
                login_count=i,
            )
        )


def test_query_primary_all(models: object) -> None:
    seed(models, 3)
    users = models.User.query.primary(org_id="acme").all()  # type: ignore[attr-defined]
    assert {u.user_id for u in users} == {"u1", "u2", "u3"}


def test_sort_key_begins_with(models: object) -> None:
    seed(models, 2)
    users = models.User.query.primary(org_id="acme").begins_with("USER#").all()  # type: ignore[attr-defined]
    assert len(users) == 2


def test_sort_key_eq(models: object) -> None:
    seed(models, 3)
    users = models.User.query.primary(org_id="acme").eq("USER#u2").all()  # type: ignore[attr-defined]
    assert [u.user_id for u in users] == ["u2"]


def test_sort_key_comparators(models: object) -> None:
    seed(models, 5)
    q = models.User.query  # type: ignore[attr-defined]
    assert {u.user_id for u in q.primary(org_id="acme").gt("USER#u3").all()} == {"u4", "u5"}
    assert {u.user_id for u in q.primary(org_id="acme").gte("USER#u3").all()} == {"u3", "u4", "u5"}
    assert {u.user_id for u in q.primary(org_id="acme").lt("USER#u3").all()} == {"u1", "u2"}
    assert {u.user_id for u in q.primary(org_id="acme").lte("USER#u3").all()} == {"u1", "u2", "u3"}


def test_sort_key_between(models: object) -> None:
    seed(models, 5)
    users = models.User.query.primary(org_id="acme").between("USER#u2", "USER#u4").all()  # type: ignore[attr-defined]
    assert {u.user_id for u in users} == {"u2", "u3", "u4"}


def test_sort_key_on_keyless_index_raises(models: object) -> None:
    # The primary key has a sort key, so build a synthetic keyless scenario:
    Membership = models.Membership  # type: ignore[attr-defined]
    builder = Membership.query.primary(org_id="acme")
    builder._key.sk_attr = None  # simulate no sort key
    with pytest.raises(ValueError):
        builder.eq("x")


def test_filter_combination(models: object) -> None:
    seed(models, 5)
    users = (
        models.User.query.primary(org_id="acme")  # type: ignore[attr-defined]
        .filter((F("status") == "active") & (F("login_count") > 2))
        .all()
    )
    assert {u.user_id for u in users} == {"u3", "u4", "u5"}


def test_chained_filters_are_anded(models: object) -> None:
    seed(models, 5)
    users = (
        models.User.query.primary(org_id="acme")  # type: ignore[attr-defined]
        .filter(F("login_count") > 1)
        .filter(F("login_count") < 4)
        .all()
    )
    assert {u.user_id for u in users} == {"u2", "u3"}


def test_query_by_gsi(models: object) -> None:
    seed(models, 3)
    user = models.User.query.by_email(email="u2@x.com").one_or_none()  # type: ignore[attr-defined]
    assert user is not None
    assert user.user_id == "u2"


def test_limit_and_iter(models: object) -> None:
    seed(models, 5)
    limited = models.User.query.primary(org_id="acme").limit(2).all()  # type: ignore[attr-defined]
    assert len(limited) == 2
    gen = models.User.query.primary(org_id="acme").iter()  # type: ignore[attr-defined]
    assert sum(1 for _ in gen) == 5


def test_first_and_descending(models: object) -> None:
    seed(models, 3)
    first_asc = models.User.query.primary(org_id="acme").first()  # type: ignore[attr-defined]
    assert first_asc is not None and first_asc.user_id == "u1"
    first_desc = models.User.query.primary(org_id="acme").descending().first()  # type: ignore[attr-defined]
    assert first_desc is not None and first_desc.user_id == "u3"


def test_one_or_none_none(models: object) -> None:
    assert models.User.query.primary(org_id="ghost").one_or_none() is None  # type: ignore[attr-defined]


def test_one_or_none_multiple_raises(models: object) -> None:
    seed(models, 2)
    with pytest.raises(MultipleResultsError):
        models.User.query.primary(org_id="acme").one_or_none()  # type: ignore[attr-defined]


def test_one_success_and_failure(models: object) -> None:
    seed(models, 1)
    user = models.User.query.primary(org_id="acme").one()  # type: ignore[attr-defined]
    assert user.user_id == "u1"
    with pytest.raises(ItemNotFoundError):
        models.User.query.primary(org_id="ghost").one()  # type: ignore[attr-defined]


def test_unknown_access_pattern_raises(models: object) -> None:
    with pytest.raises(AttributeError):
        models.User.query.nonexistent(org_id="acme")  # type: ignore[attr-defined]


def test_query_count(models: object) -> None:
    seed(models, 5)
    q = models.User.query  # type: ignore[attr-defined]
    assert q.primary(org_id="acme").count() == 5
    assert q.primary(org_id="acme").filter(F("login_count") > 2).count() == 3
    assert q.primary(org_id="ghost").count() == 0


def test_query_projection(models: object) -> None:
    seed(models, 1)
    user = (
        models.User.query.primary(org_id="acme")  # type: ignore[attr-defined]
        .attributes(["user_id", "org_id", "email", "name"])
        .one()
    )
    assert user.user_id == "u1"
    assert user.login_count == 0  # not projected -> model default


def test_scan_returns_only_this_entity(models: object) -> None:
    seed(models, 3)
    models.Membership.put(models.Membership(org_id="acme", user_id="u1"))  # type: ignore[attr-defined]
    users = models.User.scan().all()  # type: ignore[attr-defined]
    assert {u.user_id for u in users} == {"u1", "u2", "u3"}
    assert all(isinstance(u, models.User) for u in users)  # type: ignore[attr-defined]


def test_scan_filter_count_limit(models: object) -> None:
    seed(models, 5)
    assert models.User.scan().count() == 5  # type: ignore[attr-defined]
    filtered = models.User.scan().filter(F("login_count") > 3).all()  # type: ignore[attr-defined]
    assert {u.user_id for u in filtered} == {"u4", "u5"}
    assert len(models.User.scan().limit(2).all()) == 2  # type: ignore[attr-defined]


def test_scan_pagination(models: object) -> None:
    seed(models, 5)
    page = models.User.scan().limit(2).page()  # type: ignore[attr-defined]
    assert len(page.items) == 2
    assert page.cursor is not None
    rest = models.User.scan().page(cursor=page.cursor)  # type: ignore[attr-defined]
    assert len(rest.items) >= 1
