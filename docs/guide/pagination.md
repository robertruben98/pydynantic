# Pagination

For large result sets, fetch one page at a time and resume with an opaque **cursor**.
`.page()` returns a [`Page`][pydynantic.Page]; its `cursor` is safe to hand to an HTTP
client or store in JSON.

## Paging through a query

```python
page = User.query.primary(org_id="acme").limit(25).page()

page.items        # list[User]
page.cursor       # opaque token, or None when the result set is exhausted
page.has_more     # True while a cursor was returned

next_page = User.query.primary(org_id="acme").limit(25).page(cursor=page.cursor)
```

`.page()` is available on queries, scans, and collections.

## The cursor is opaque

A cursor is a versioned, base64url token **without** `=` padding, so it embeds directly
in URLs, query strings and JSON bodies. Treat it as a black box:

- Pass back **verbatim** whatever `page.cursor` produced.
- Never hand-build, mutate, or parse a cursor.

A stale, malformed, or wrong-version cursor fails **loudly** — `decode_cursor` raises
[`PydynanticError`][pydynantic.PydynanticError] rather than silently misbehaving.

!!! note "Not signed"
    Cursors are not HMAC-signed. They encode only a DynamoDB key the caller could already
    query directly, so there is no secret to protect; versioning plus validation buys
    well-defined failure without key management.

## Looping over all pages

For an HTTP API you typically return one page per request (see the
[recipes](../recipes.md)). To drain everything in a worker, either use `.all()` /
`.iter()` (which paginate internally) or loop on the cursor:

```python
cursor = None
while True:
    page = User.query.primary(org_id="acme").limit(100).page(cursor=cursor)
    for user in page.items:
        process(user)
    if not page.has_more:
        break
    cursor = page.cursor
```

## Low-level helpers

[`encode_cursor`][pydynantic.encode_cursor] and
[`decode_cursor`][pydynantic.decode_cursor] convert between a DynamoDB
`LastEvaluatedKey` and the opaque token. You rarely call these directly — `.page()` does
it for you — but they are exported for advanced integrations.
