# Filters & conditions

`pydynantic` builds DynamoDB expressions from a small fluent DSL, so you never juggle
`ExpressionAttributeNames` / `ExpressionAttributeValues` or risk placeholder collisions.
The same [`Condition`][pydynantic.Condition] objects power both **filters** (narrow query
results) and **conditions** (guard writes).

## Building conditions with `F`

[`F`][pydynantic.F] references an attribute by name; comparing it produces a `Condition`:

```python
from pydynantic import F

F("status") == "active"
F("login_count") > 0
F("name") != "Ana"
```

Operators and methods:

| Expression | Meaning |
| --- | --- |
| `F("a") == v`, `!= v`, `< v`, `<= v`, `> v`, `>= v` | comparisons |
| `F("a").between(lo, hi)` | inclusive range |
| `F("a").begins_with(prefix)` | string prefix |
| `F("a").contains(v)` | substring / set membership |
| `F("a").is_in([v1, v2])` | one of a list |
| `F("a").exists()` / `F("a").not_exists()` | attribute presence |

## Combining conditions

Combine with `&` (AND), `|` (OR) and `~` (NOT). Parenthesize to make precedence explicit:

```python
(F("status") == "active") & (F("login_count") > 0)
(F("status") == "active") | (F("status") == "trial")
~(F("status") == "banned")
```

## Filters on queries and scans

`.filter(...)` applies a `FilterExpression` *after* the key condition. It narrows the
returned items but is billed on items read, so it complements — never replaces — a good
key design.

```python
(User.query.primary(org_id="acme")
     .filter((F("status") == "active") & (F("login_count") > 0))
     .all())

User.scan().filter(F("status") == "active").count()
```

## Conditions on writes

Pass a `condition=` to [`put()`][pydynantic.Entity.put],
[`update()`][pydynantic.Entity.update] or [`delete()`][pydynantic.Entity.delete] to make
the write conditional. A failed guard raises
[`ConditionCheckFailedError`][pydynantic.ConditionCheckFailedError].

```python
# Create-only put — fails if the item already exists.
from pydynantic import attr_not_exists
User.put(user, condition=attr_not_exists("PK"))

# Conditional update — only deactivate an account that is currently active.
User.update(
    org_id="acme", user_id="u1",
    set={"status": "inactive"},
    condition=F("status") == "active",
)
```

### `attr_exists` / `attr_not_exists`

[`attr_exists`][pydynantic.attr_exists] and
[`attr_not_exists`][pydynantic.attr_not_exists] are convenience helpers that build a
presence condition on a raw attribute path — handy for create-only or update-only
guards keyed on the physical `PK`:

```python
from pydynantic import attr_exists, attr_not_exists

User.put(user, condition=attr_not_exists("PK"))         # must NOT already exist
User.delete(org_id="acme", user_id="u1",
            condition=attr_exists("PK"))                # must already exist
```

!!! note
    `ExpressionAttributeNames` and `ExpressionAttributeValues` are generated for you with
    collision-free `#name` / `:value` placeholders — even for dotted attribute paths and
    repeated attributes.
