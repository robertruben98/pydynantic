"""A runnable, end-to-end pydynantic example: a multi-tenant SaaS data model.

This single file models four entities in ONE DynamoDB table (single-table
design) and exercises the whole public surface of pydynantic:

    * a Table + entities with key templates and a GSI;
    * CRUD (put / get / update / delete);
    * a query by primary key and a query by GSI (``by_email``);
    * a filter expression with ``F(...)``;
    * cursor pagination (``.page(cursor=...)``);
    * batch write / batch get;
    * an atomic transaction (``with transaction(table) as tx: ...``);
    * a collection query over a single partition;
    * optimistic locking via ``version_attr()`` plus auto-timestamps.

It runs with NO AWS credentials: everything happens against moto's in-memory
DynamoDB (``mock_aws``). Just::

    pip install -e ".[dev]"
    python examples/saas_app.py

The script prints readable output as it goes and ends with a success line.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
from typing import Any

import boto3
from moto import mock_aws

from pydynantic import (
    Collection,
    Entity,
    F,
    Field,
    OptimisticLockError,
    Table,
    attr_not_exists,
    created_at_attr,
    key,
    transaction,
    updated_at_attr,
    version_attr,
)

TABLE_NAME = "saas-app"


# --------------------------------------------------------------------------- #
# 1. The physical table.                                                       #
# --------------------------------------------------------------------------- #
def create_table(client: Any) -> None:
    """Provision the single physical table + one GSI (the GSI for ``by_email``).

    In production you'd do this with CDK/Terraform; here we call the raw boto3
    API so the example is self-contained against moto.
    """
    client.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


# --------------------------------------------------------------------------- #
# 2. The data model.                                                           #
# --------------------------------------------------------------------------- #
class Plan(str, Enum):
    """Subscription tier an organisation is on."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


def build_models(table: Table) -> SimpleNamespace:
    """Declare the SaaS entities bound to ``table`` and return them.

    Entities self-register with their table at class-creation time, so they're
    defined here (inside the mock) rather than at import time.
    """

    class Org(Entity, table=table, name="org"):
        """A tenant. Everything else hangs off an org's partition."""

        org_id: str
        display_name: str
        plan: Plan = Plan.FREE
        seats: int = 5
        # Plain Pydantic Field works exactly as you'd expect on entities.
        signed_up_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

        class Meta:
            # ORG#{org_id} is the shared partition for this tenant's data.
            primary = key(pk="ORG#{org_id}", sk="ORG#{org_id}")

    class User(Entity, table=table, name="user"):
        """A person in an org. Also indexed by email for global lookup."""

        user_id: str
        org_id: str
        email: str
        name: str
        active: bool = True
        login_count: int = 0
        created_at: datetime | None = created_at_attr()
        updated_at: datetime | None = updated_at_attr()

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
            # GSI: find a user by email without knowing their org.
            by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")

    class Project(Entity, table=table, name="project"):
        """A project inside an org, with optimistic-locking on writes."""

        project_id: str
        org_id: str
        title: str
        archived: bool = False
        version: int = version_attr()

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="PROJECT#{project_id}")

    class Membership(Entity, table=table, name="membership"):
        """Links a user to an org with a role; lives in the org partition."""

        org_id: str
        user_id: str
        role: str = "member"

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="MEMBER#{user_id}")

    class OrgData(Collection):
        """Read several entity types from one org partition in a single query."""

        members = [User, Project, Membership]

    return SimpleNamespace(
        Org=Org,
        User=User,
        Project=Project,
        Membership=Membership,
        OrgData=OrgData,
    )


# --------------------------------------------------------------------------- #
# 3. The walkthrough.                                                          #
# --------------------------------------------------------------------------- #
def run(m: SimpleNamespace, table: Table) -> None:
    """Exercise the library end to end, printing what happens at each step."""
    Org, User, Project, Membership, OrgData = (
        m.Org,
        m.User,
        m.Project,
        m.Membership,
        m.OrgData,
    )

    print("== CRUD: create an org and some users ==")
    Org.put(Org(org_id="acme", display_name="Acme Inc.", plan=Plan.PRO, seats=25))
    Org.put(Org(org_id="globex", display_name="Globex", plan=Plan.FREE))

    User.put(User(user_id="u1", org_id="acme", email="ana@acme.com", name="Ana"))
    User.put(User(user_id="u2", org_id="acme", email="bob@acme.com", name="Bob"))
    User.put(User(user_id="u3", org_id="acme", email="cara@acme.com", name="Cara"))
    User.put(User(user_id="g1", org_id="globex", email="dan@globex.com", name="Dan"))

    ana = User.get(org_id="acme", user_id="u1")
    assert ana is not None
    print(f"  fetched: {ana.name} <{ana.email}> created_at={ana.created_at:%Y-%m-%d}")

    # update() generates the UpdateExpression for you; add= is atomic.
    User.update(org_id="acme", user_id="u1", set={"name": "Ana B."}, add={"login_count": 3})
    ana = User.get(org_id="acme", user_id="u1")
    assert ana is not None
    print(f"  after update: {ana.name}, login_count={ana.login_count}")

    print("\n== Query by primary key (one org's users) ==")
    acme_users = User.query.primary(org_id="acme").begins_with("USER#").all()
    print(f"  acme has {len(acme_users)} users: {[u.name for u in acme_users]}")

    print("\n== Query by GSI (by_email) ==")
    by_email = User.query.by_email(email="bob@acme.com").one_or_none()
    assert by_email is not None
    print(f"  EMAIL#bob@acme.com -> {by_email.name} (org={by_email.org_id})")

    print("\n== Filter expression with F(...) ==")
    # Deactivate one user, then count the active ones server-side.
    User.update(org_id="acme", user_id="u3", set={"active": False})
    active_count = User.query.primary(org_id="acme").filter(F("active") == True).count()  # noqa: E712
    print(f"  active acme users (server-side count): {active_count}")

    print("\n== Batch write + batch get ==")
    Membership.batch_write(
        puts=[
            Membership(org_id="acme", user_id="u1", role="owner"),
            Membership(org_id="acme", user_id="u2", role="admin"),
            Membership(org_id="acme", user_id="u3", role="member"),
        ]
    )
    fetched = Membership.batch_get([("acme", "u1"), ("acme", "u2"), ("acme", "u3")])
    roles = {mem.user_id: mem.role for mem in fetched}
    print(f"  memberships: {roles}")

    print("\n== Pagination (.page(cursor=...)) ==")
    seen: list[str] = []
    cursor: str | None = None
    page_no = 0
    while True:
        page = User.query.primary(org_id="acme").begins_with("USER#").limit(2).page(cursor=cursor)
        page_no += 1
        seen.extend(u.user_id for u in page.items)
        print(f"  page {page_no}: {[u.user_id for u in page.items]} has_more={page.has_more}")
        if not page.has_more:
            break
        cursor = page.cursor
    print(f"  paged through {len(seen)} users in {page_no} pages")

    print("\n== Transaction (atomic put + update) ==")
    # Create a project AND bump the org's seat usage as one all-or-nothing unit.
    with transaction(table) as tx:
        tx.put(Project(project_id="p1", org_id="acme", title="Website revamp"))
        tx.update(Org, key=("acme", "acme"), add={"seats": 1})
    org = Org.get(org_id="acme")
    assert org is not None
    print(f"  committed: project p1 created, acme seats now {org.seats}")

    print("\n== Optimistic locking (version_attr) ==")
    proj = Project.get(org_id="acme", project_id="p1")
    assert proj is not None
    print(f"  loaded project at version {proj.version}")
    # A versioned put guards on the prior version; a stale write loses the race.
    Project.put(Project(project_id="p1", org_id="acme", title="Website revamp v2"))
    stale = Project(project_id="p1", org_id="acme", title="conflict", version=proj.version)
    try:
        Project.put(stale)
    except OptimisticLockError:
        print("  stale write rejected with OptimisticLockError (as expected)")
    current = Project.get(org_id="acme", project_id="p1")
    assert current is not None
    print(f"  winning title='{current.title}' at version {current.version}")

    print("\n== Collection query (several entities, one partition) ==")
    result = OrgData.query(org_id="acme").all()
    print(
        f"  acme partition -> {len(result.users)} users, "
        f"{len(result.projects)} projects, {len(result.memberships)} memberships"
    )

    print("\n== Conditional create + delete ==")
    # attr_not_exists makes put() a create-only operation.
    User.put(
        User(user_id="u4", org_id="acme", email="eve@acme.com", name="Eve"),
        condition=attr_not_exists("PK"),
    )
    print("  created u4 (Eve) with create-only condition")
    User.delete(org_id="acme", user_id="u4")
    print("  deleted u4; get now returns:", User.get(org_id="acme", user_id="u4"))


def main() -> None:
    """Run the whole example against an in-memory DynamoDB."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_table(client)
        table = Table(
            name=TABLE_NAME,
            indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
            client=client,
        )
        models = build_models(table)
        run(models, table)
        print(f"\nDone at {datetime.now(timezone.utc):%H:%M:%S}Z -- example ran end-to-end. ✅")


if __name__ == "__main__":
    main()
