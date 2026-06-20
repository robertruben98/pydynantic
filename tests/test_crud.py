"""Tests for put / get / update / delete and conditions."""

from __future__ import annotations

import pytest

from pydynantic import Entity, F, attr_not_exists, key
from pydynantic.errors import ConditionCheckFailedError, ItemNotFoundError, PydynanticError


def make_user(models: object, **overrides: object) -> object:
    User = models.User  # type: ignore[attr-defined]
    defaults = {"user_id": "u1", "org_id": "acme", "email": "a@x.com", "name": "Ana"}
    defaults.update(overrides)
    return User(**defaults)


def test_put_and_get(models: object) -> None:
    models.User.put(make_user(models))  # type: ignore[attr-defined]
    fetched = models.User.get(org_id="acme", user_id="u1")  # type: ignore[attr-defined]
    assert fetched is not None
    assert fetched.email == "a@x.com"
    assert fetched.name == "Ana"


def test_get_missing_returns_none(models: object) -> None:
    assert models.User.get(org_id="acme", user_id="nope") is None  # type: ignore[attr-defined]


def test_get_or_raise(models: object) -> None:
    with pytest.raises(ItemNotFoundError):
        models.User.get_or_raise(org_id="acme", user_id="nope")  # type: ignore[attr-defined]


def test_put_create_only_condition(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models))
    with pytest.raises(ConditionCheckFailedError):
        User.put(make_user(models, name="dup"), condition=attr_not_exists("PK"))


def test_delete(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models))
    User.delete(org_id="acme", user_id="u1")
    assert User.get(org_id="acme", user_id="u1") is None


def test_delete_with_failing_condition(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models))
    with pytest.raises(ConditionCheckFailedError):
        User.delete(org_id="acme", user_id="u1", condition=F("name") == "wrong")


def test_delete_returns_old_item(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models))
    old = User.delete(org_id="acme", user_id="u1", return_values="ALL_OLD")
    assert old is not None
    assert old.email == "a@x.com"
    assert User.get(org_id="acme", user_id="u1") is None


def test_delete_missing_returns_none_with_all_old(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    assert User.delete(org_id="acme", user_id="nope", return_values="ALL_OLD") is None


def test_delete_default_returns_none(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models))
    assert User.delete(org_id="acme", user_id="u1") is None


def test_delete_invalid_return_values_raises(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    with pytest.raises(PydynanticError):
        User.delete(org_id="acme", user_id="u1", return_values="ALL_NEW")


def test_put_invalid_return_values_raises(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    with pytest.raises(PydynanticError):
        User.put(make_user(models), return_values="ALL_NEW")


def test_put_all_old_still_returns_written_item(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models, name="Ana"))
    modified = make_user(models, name="Ana B.")
    result = User.put(modified, return_values="ALL_OLD")
    assert result is modified
    assert result.name == "Ana B."


def test_update_set_and_add(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models, login_count=0))
    updated = User.update(
        org_id="acme",
        user_id="u1",
        set={"name": "Ana B."},
        add={"login_count": 2},
    )
    assert updated is not None
    assert updated.name == "Ana B."
    assert updated.login_count == 2


def test_update_remove(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models, name="Ana"))
    updated = User.update(org_id="acme", user_id="u1", remove=["login_count"])
    assert updated is not None
    assert updated.login_count == 0  # default re-applied on read


def test_update_recomputes_gsi_key_on_status_change(models: object) -> None:
    """Changing ``status`` should keep the by_status GSI key consistent."""
    User = models.User  # type: ignore[attr-defined]
    Status = models.Status  # type: ignore[attr-defined]
    User.put(make_user(models, status=Status.ACTIVE))
    User.update(org_id="acme", user_id="u1", set={"status": Status.INACTIVE})

    # The user must now be reachable via the by_status GSI under INACTIVE.
    found = User.query.by_status(org_id="acme", status=Status.INACTIVE).all()
    assert [u.user_id for u in found] == ["u1"]
    assert User.query.by_status(org_id="acme", status=Status.ACTIVE).all() == []


def test_update_with_condition_failure(models: object) -> None:
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models, name="Ana"))
    with pytest.raises(ConditionCheckFailedError):
        User.update(
            org_id="acme",
            user_id="u1",
            set={"name": "X"},
            condition=F("name") == "wrong",
        )


def test_update_requires_a_clause(models: object) -> None:
    from pydynantic.errors import PydynanticError

    with pytest.raises(PydynanticError):
        models.User.update(org_id="acme", user_id="u1")  # type: ignore[attr-defined]


def test_update_changing_status_recomputes_gsi(models: object) -> None:
    """A GSI whose source fields are all derivable is recomputed silently."""
    User = models.User  # type: ignore[attr-defined]
    User.put(make_user(models, status=models.Status.ACTIVE))  # type: ignore[attr-defined]
    User.update(org_id="acme", user_id="u1", set={"status": models.Status.INACTIVE})  # type: ignore[attr-defined]
    # by_status keys on org_id + status + user_id, all known on update.
    found = User.query.by_status(org_id="acme", status="inactive").all()
    assert {u.user_id for u in found} == {"u1"}


def test_update_raises_when_gsi_cannot_be_recomputed(models: object) -> None:
    table = models.table  # type: ignore[attr-defined]

    class Doc(Entity, table=table, name="doc_guard"):
        org_id: str
        doc_id: str
        status: str = "open"
        category: str = "x"

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="DOC#{doc_id}")
            by_cat = key(index="GSI1", pk="CAT#{category}", sk="ST#{status}#{doc_id}")

    Doc.put(Doc(org_id="acme", doc_id="d1", status="open", category="legal"))

    # Updating only ``status`` cannot rebuild the GSI key (needs ``category``),
    # so the update must refuse rather than silently leave the index stale.
    with pytest.raises(PydynanticError, match="by_cat"):
        Doc.update(org_id="acme", doc_id="d1", set={"status": "closed"})

    # Supplying every source field lets the index be recomputed.
    Doc.update(org_id="acme", doc_id="d1", set={"status": "closed", "category": "legal"})
    got = Doc.query.by_cat(category="legal").begins_with("ST#closed").all()
    assert len(got) == 1
