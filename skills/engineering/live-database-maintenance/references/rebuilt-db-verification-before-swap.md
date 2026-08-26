# Verifying a rebuilt database before you swap it in

**Six real bugs, one session (one occasion).** Every one passed
`PRAGMA integrity_check` and would have shipped silently. The lesson is that
**`integrity: ok` on the new file proves nothing about whether the rebuild
preserved your data** — you must diff the rebuilt copy against the source.

## 1. `text_factory = bytes` silently converts every TEXT column to BLOB

Set on the reader so odd encodings can't abort a long copy. Consequence:

```
SOURCE: typeof(source) = text -> where source='telegram' -> 326
REBUILT: typeof(source) = blob -> where source='telegram' -> 0
```

Every byte present, `integrity_check: ok`, search returning hits — and the
application reads the database as **completely empty**. Total silent data loss
that passes every health check.

Fix: preserve text, degrade only on genuinely undecodable bytes.

```python
src.text_factory = lambda b: b.decode("utf-8", errors="replace")
```

Read the schema BEFORE changing `text_factory`, or `sqlite_master` rows come
back as bytes and `name.startswith(...)` raises `TypeError`.

Guard it in the fixture test and mutation-test the guard:

```python
for tbl, col in (("sessions", "source"), ("messages", "content")):
    kinds = c.execute(f"select typeof({col}), count(*) from {tbl} group by 1")
    assert all(k in ("text", "null", "integer") for k, _ in kinds)
```

## 2. `max(rowid)` is meaningless on TEXT / composite primary keys

A high-water delta sync works for `messages` (INTEGER pk). It is nonsense for
`sessions` (TEXT pk `id`), `system_prompts` (TEXT pk `hash`), and
`session_model_usage` (composite pk) — a rebuild renumbers rowids, so the sync
reported "1,344 new sessions" out of 3,638.

Check `pragma table_info` for the real pk, then: incremental for INTEGER pks,
**full re-sync with `INSERT OR REPLACE`** for everything else (cheap at these
row counts, correct regardless of key shape).

## 3. A corrupt source needs read-side degradation, not just write-side

One `SELECT` spanning a corrupt page raises `database disk image is malformed`
and the **entire** delta sync yields 0 rows. Verification then correctly refuses
the swap, and it reads like the rebuild failed.

Degrade the READ: chunk → bisect → single row, counting what is truly
unreadable.

```python
def read_range(table, cols, key, lo, hi):
    try:
        return src.execute(f"select {cols} from {table} "
                           f"where {key} >= ? and {key} < ?", (lo, hi)).fetchall(), 0
    except Exception:
        if hi - lo <= 1:
            return [], 1
        mid = (lo + hi) // 2
        a, ab = read_range(table, cols, key, lo, mid)
        b, bb = read_range(table, cols, key, mid, hi)
        return a + b, ab + bb
```

## 4. PHANTOM ROWS — `count(*)` on a corrupt B-tree lies

The single most confusing finding. Measured:

```
live count(*) 455,522
live actually readable 455,487 <- 1,937 PHANTOM rows
rebuilt 455,483
```

A damaged B-tree counts rows from interior-page metadata that it **cannot
produce**. Verifying `new_count >= live_count(*)` blocks the swap forever over
data that does not exist.

**Compare readable-to-readable**: enumerate ids on both sides and diff the sets.
Allow a small bounded shortfall, print the unrecoverable ids explicitly, and
refuse anything larger:

```
sessions live readable=3638 new=3635 missing=3 (tolerance 20) OK
  unrecoverable ids: ['20260822_173623_b6fe1e',...]
messages live readable=455487 new=455483 missing=4 (tolerance 22) OK
  unrecoverable ids: [976098, 976116, 976117, 976118]
```

Also: "missing" rows are often just **newer than the snapshot**. Diff by id
before concluding loss — here every apparent gap above the high-water mark was
live traffic during the copy, and true loss was 4 messages, all created inside
the corruption window.

## 5. Holding down a `Restart=always` service

`systemctl stop` is undone 5s later. `systemctl mask` **fails** when the unit is
a real file (`Failed to mask unit: File... already exists`) — it only works on
symlinks. The lever that works is a drop-in, removed in an `EXIT` trap:

```bash
DROPIN=$HOME/.config/systemd/user/$UNIT.d/zz-maintenance.conf
printf '[Service]\nRestart=no\n' > "$DROPIN"
systemctl --user daemon-reload
```

Wait on the unit reaching a settled state, not a fixed poll: a busy agent drains
before exiting (measured **195s** — "Gateway drain timed out after 180.0s with 1
active agent(s), 2 in-flight cron job(s)"). A 45s wait aborts safely but wastes
a cycle. With owner approval, 25s grace then `SIGKILL` cut it to **5-10s**; safe
here because the file is about to be replaced wholesale and the catch-up sync
runs _after_ the process is gone.

## 6. Re-assert the invariant between steps

A catch-up pass that opens the live file leaves a holder; the swap's own guard
then aborts with "gateway still holds the database". Re-check and clear holders
immediately before the rename rather than failing the whole run.

## The shape that works

```
rebuild (snapshot) -> stop service -> catch-up delta -> verify -> swap -> start
```

Verification gates the rename and aborts on ANY failure, leaving the live file
untouched. That design held through five aborted attempts — the live database
was never damaged by a failed run. **Keep the abort-on-failure gate even when it
is the thing rejecting your work**; each refusal here was a real bug.

Retain the displaced corrupt file (`state.db.corrupt-<stamp>`) until the
replacement has served real traffic.
