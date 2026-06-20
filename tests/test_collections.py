"""Tests for retrieving multiple entity types from one partition."""

from __future__ import annotations

from decimal import Decimal


def test_collection_buckets_by_entity(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    Invoice = models.Invoice  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]

    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    User.put(User(user_id="u2", org_id="acme", email="b@x.com", name="Bob"))
    Membership.put(Membership(org_id="acme", user_id="u1", role="admin"))
    Invoice.put(Invoice(org_id="acme", invoice_id="i1", amount=Decimal("99.50")))

    result = OrgData.query(org_id="acme").all()

    assert {u.user_id for u in result.users} == {"u1", "u2"}
    assert [m.role for m in result.memberships] == ["admin"]
    assert [inv.amount for inv in result.invoices] == [Decimal("99.50")]
    assert all(isinstance(u, User) for u in result.users)
    assert all(isinstance(inv, Invoice) for inv in result.invoices)


def test_collection_all_merges(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]

    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    Membership.put(Membership(org_id="acme", user_id="u1", role="admin"))

    result = OrgData.query(org_id="acme").all()
    assert len(result.all()) == 2


def test_collection_projection_buckets(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]

    # Projection attributes are User fields; seed only Users so every projected
    # item can still construct (a cross-entity projection cannot satisfy members
    # whose required fields are projected away).
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    User.put(User(user_id="u2", org_id="acme", email="b@x.com", name="Bob"))

    # A projection that omits __entity__ would drop every item; the query must
    # auto-include the discriminator so bucketing still works.
    result = OrgData.query(org_id="acme", attributes=["user_id", "org_id", "email", "name"]).all()

    assert {u.user_id for u in result.users} == {"u1", "u2"}
    assert all(isinstance(u, User) for u in result.users)


def test_collection_projection_omits_field(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]

    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana", login_count=42))

    result = OrgData.query(org_id="acme", attributes=["user_id", "org_id", "email", "name"]).all()

    # login_count was projected away, so it falls back to its model default.
    assert [u.login_count for u in result.users] == [0]


def test_collection_empty_partition(models: object) -> None:
    result = models.OrgData.query(org_id="ghost").all()  # type: ignore[attr-defined]
    assert result.users == []
    assert result.invoices == []


def test_collection_unknown_bucket_raises(models: object) -> None:
    result = models.OrgData.query(org_id="acme").all()  # type: ignore[attr-defined]
    import pytest

    with pytest.raises(AttributeError):
        _ = result.widgets


def _seed_mixed(models: object, count: int = 5) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    Invoice = models.Invoice  # type: ignore[attr-defined]
    for i in range(count):
        User.put(User(user_id=f"u{i}", org_id="acme", email=f"u{i}@x.com", name=f"N{i}"))
        Membership.put(Membership(org_id="acme", user_id=f"u{i}", role="member"))
        Invoice.put(Invoice(org_id="acme", invoice_id=f"i{i}", amount=Decimal("1")))


def test_collection_limit_bounds_items_read(models: object) -> None:
    OrgData = models.OrgData  # type: ignore[attr-defined]
    _seed_mixed(models, count=5)

    page = OrgData.query(org_id="acme").limit(2).page()
    assert len(page.result.all()) <= 2


def test_collection_page_walks_all(models: object) -> None:
    OrgData = models.OrgData  # type: ignore[attr-defined]
    _seed_mixed(models, count=5)

    full = OrgData.query(org_id="acme").all()
    expected = {
        "users": {u.user_id for u in full.users},
        "memberships": {m.user_id for m in full.memberships},
        "invoices": {inv.invoice_id for inv in full.invoices},
    }

    seen_users: set[str] = set()
    seen_memberships: set[str] = set()
    seen_invoices: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        page = OrgData.query(org_id="acme").limit(2).page(cursor=cursor)
        seen_users |= {u.user_id for u in page.result.users}
        seen_memberships |= {m.user_id for m in page.result.memberships}
        seen_invoices |= {inv.invoice_id for inv in page.result.invoices}
        pages += 1
        if not page.has_more:
            break
        cursor = page.cursor
        assert pages < 100  # guard against an infinite loop

    assert seen_users == expected["users"]
    assert seen_memberships == expected["memberships"]
    assert seen_invoices == expected["invoices"]


def test_collection_page_cursor_none_when_drained(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))

    page = OrgData.query(org_id="acme").page()
    assert page.cursor is None
    assert page.has_more is False


def test_collection_page_respects_projection(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    User.put(User(user_id="u2", org_id="acme", email="b@x.com", name="Bob"))

    page = OrgData.query(org_id="acme", attributes=["user_id", "org_id", "email", "name"]).page()

    assert {u.user_id for u in page.result.users} == {"u1", "u2"}
    assert all(isinstance(u, User) for u in page.result.users)


def test_collection_invalid_cursor_raises(models: object) -> None:
    import pytest

    from pydynantic import PydynanticError

    OrgData = models.OrgData  # type: ignore[attr-defined]
    with pytest.raises(PydynanticError):
        OrgData.query(org_id="acme").page(cursor="not-a-valid-cursor!!!")


def test_collection_all_still_drains(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    Membership = models.Membership  # type: ignore[attr-defined]
    OrgData = models.OrgData  # type: ignore[attr-defined]
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))
    Membership.put(Membership(org_id="acme", user_id="u1", role="admin"))

    # A limit set on the builder must not affect all(): it still drains.
    result = OrgData.query(org_id="acme").limit(1).all()
    assert len(result.all()) == 2
