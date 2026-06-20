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
