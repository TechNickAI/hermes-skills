# Silent zero-result query traps

A sibling of `silent-extraction-failure-as-false-negative.md`. There, the decoder
was broken and returned empty-looking content. Here, the **decoder works fine** and
the _filter_ silently excludes every row. Both produce the same output — an empty
result set, exit code 0, no error — and both become a confident false negative if
you report the result instead of auditing the query.

Rule for the whole class: **a filtered query must print its scan count.** A result
of `0 matches` is only meaningful next to `scanned 3,493 rows`. A result of
`0 matches / scanned 0` is a bug in the query, never a fact about the world.

```python
n = 0
for row in db.execute(q):
    n += 1
    ...
print('scanned', n)          # ← mandatory, not optional
```

If the scan count is zero against a store you know is populated, stop and fix the
query. Do not report a finding.

## Trap: SQLite type affinity makes date filters match nothing

Measured on one run while searching a 176,837-row `chat.db`. This filter returned
**zero rows** with no error:

```sql
WHERE m.date/1000000000 + 978307200 > strftime('%s','now','-14 days')
```

`strftime('%s',...)` returns a **TEXT** value. The left side is an INTEGER
expression. SQLite compares INTEGER against TEXT using storage-class ordering, in
which every integer sorts _before_ every string, so the predicate is false for
every row in the table. Forever. Silently.

```sql
-- correct
WHERE m.date/1000000000 + 978307200 > CAST(strftime('%s','now','-14 days') AS INTEGER)
```

The diagnostic that caught it was a three-line control query, not more staring at
the WHERE clause:

```python
print(db.execute("select count(*) from message").fetchone())                     # 176837
print(db.execute("select datetime(max(date)/1000000000+978307200,'unixepoch') from message").fetchone())
print(db.execute("select count(*) from message where <the filter>").fetchone())  # 0  ← the bug
```

Total rows non-zero, max timestamp recent, filtered count zero. That triple
localizes the fault to the predicate in one call.

## Generalize: the control-query triple

Any time a filtered read comes back empty, run three queries before believing it:

1. **Unfiltered count** — proves the table/store is populated at all.
2. **Extremum of the filter column** — proves the data covers the range you asked
   for (max timestamp, max id, distinct values).
3. **The filtered count itself.**

If (1) and (2) are healthy and (3) is zero, the predicate is wrong. Common causes
beyond type affinity: unit mismatch (ns vs. µs vs. s), epoch offset omitted, a
`LIKE` pattern missing wildcards, a JOIN that drops rows with NULL foreign keys
(`LEFT JOIN` vs. `JOIN` on a nullable handle/user column), and a masked or
redacted column that can never match a literal you grep for.

## Trap: redacted API output cannot be used as a lookup key

A CLI's JSON may mask the very field you want to search on. Example: `imsg chats
--json` returns `"identifier": "+130****3071"`. That value is fine for _display_
and useless for _lookup_ — you cannot match it against a known phone number, and
grepping for a real number finds nothing.

When a CLI's output is masked, drop to the underlying store where the field is
intact, then pivot back. The general move: **find the entity by its unmasked key
in the raw store, collect ALL of its ids, then query across every one of them.**
A single person routinely owns many handle rows and many conversation rows (one
per 1:1 plus one per group). Reading one and calling it the full correspondence
is the same class of error as a filter that matches nothing — a partial read
presented as a complete answer.

## Reporting rule: a one-sided record means an unseen surface

When a thread returns only the other party's messages, and their replies clearly
respond to something ("great! Looking forward to working on this together"), your
side happened somewhere this store cannot see — a different account, a phone call,
another platform, or an unsynced device.

Do **not** write "you never replied," and do **not** reconstruct the missing half
from context. Both put words in the user's mouth about a commitment they may have
made differently. Name the boundary and hand it back:

> His replies imply you answered on a surface I can't see. Tell me what you told
> him — I'm not going to guess at a commitment you made.

This is the same discipline as Step 0 in the parent skill: absence of retrievable
evidence is a statement about your read path, not about what happened.

## Checklist

- [ ] Every filtered query prints its scan count alongside its match count
- [ ] Zero matches triggered the control-query triple before any reporting
- [ ] Date/time predicates `CAST(...)` string functions to INTEGER
- [ ] Lookup keys taken from the raw store, never from masked/redacted CLI output
- [ ] All of an entity's ids enumerated, not just the first one found
- [ ] One-sided records reported as a visibility boundary, never as a non-event
