# Offline FTS rebuild and whole-file swap on an auto-restarting service

Measured 2026-08-22 on the fleet's busiest Hermes profile (455k messages,
3.0 GB `state.db`), which had corrupted repeatedly over three days. Every
section below is a place where the obvious move fails silently or destructively.

## 1. The damage is in the BASE table even when only FTS looks broken

Symptom sequence that misleads: a per-table scan names only FTS tables as
`BAD`, so it reads as "the index is corrupt, rebuild it." Four rebuild attempts
each re-derived the corruption.

The falsifier is to **remove every FTS object and re-run
`integrity_check`**. Here that returned `real problems: NONE` — and then
recreating the index immediately reproduced `malformed`. That proves the fault
is in the source data, not the index.

Reading the full unsliced check confirmed it:

```
Tree 3  page 1678   cell 399: Rowid 5015 out of order
Tree 5  page 497514 cell 0:   invalid page number 218103809
Tree 5  page 582243 cell 248: 2nd reference to page 697450
Tree 35 page 355281 cell 61:  2nd reference to page 595150
```

Pages referenced twice, an impossible page number, rowids out of order:
**structural B-tree corruption in `messages`**. A sequential `count(*)` never
walks the broken interior pointers, so the table scans clean; building an index
does walk them, which is why FTS is where it surfaces. **A table that passes
`select count(*)` is not proven intact.**

Rule: when repairing an index "fixes" nothing twice, stop repairing the index.

## 2. A corrupt fts5 vtable cannot be DROPped, and half-dropping it is worse

`INSERT INTO fts(fts) VALUES('rebuild')` fails on a corrupt index — rebuild
still reads the existing shadow structure.

So does `DROP TABLE messages_fts`: **dropping an fts5 virtual table requires
CONSTRUCTING it first.** Both raise `database disk image is malformed`.

🔴 The destructive trap: a script that runs `DROP TABLE IF EXISTS <vtable>`,
ignores the failure, and then deletes the shadow tables (`_idx`, `_config`,
`_data`, `_docsize`) anyway leaves the virtual table **registered in
`sqlite_master` but unconstructable**. State goes from "search degraded" to
"`PRAGMA integrity_check` itself raises":

```
quick_check: OperationalError: vtable constructor failed: messages_fts
```

You have now blinded every diagnostic you were relying on. Never delete shadow
tables on the failure path of a `DROP` — gate the cleanup on the `DROP`
succeeding.

**Escape hatch** when already in that state — delete the schema rows directly:

```python
conn.execute("PRAGMA writable_schema=ON")
conn.execute("DELETE FROM sqlite_master WHERE name LIKE 'messages_fts%'")
conn.commit()
conn.execute("PRAGMA writable_schema=OFF")
conn.close()          # reopen: the schema cache must be rebuilt from disk
```

Then recreate from captured DDL. Capture that DDL **before** touching anything
(`select name, sql from sqlite_master`), including any VIEW the index reads.

## 3. Recreate the source VIEW before the external-content index

`messages_fts_trigram` is `content='messages_fts_trigram_src'`, and that source
is a **VIEW**, not a table:

```sql
CREATE VIEW messages_fts_trigram_src AS
  SELECT id, role, content, tool_name, tool_calls FROM messages
  WHERE role <> 'tool'
```

Two ordering bugs cost a full rebuild each:

- A rebuild loop that creates tables, then indexes, then views fails with
  `no such table: main.messages_fts_trigram_src`. An external-content FTS table
  resolves its source at CREATE time. **Sort views ahead of everything else.**
- A skip-list of `messages_fts*` (to avoid copying corrupt indexes) also
  excludes `messages_fts_trigram_src`, because the view shares the prefix.
  Carry an explicit keep-list.

## 4. `text_factory = bytes` silently produces an unreadable database

Setting `text_factory = bytes` on the reader — a reasonable-looking defense so
one undecodable row cannot abort a long copy — makes SQLite store **every TEXT
column as BLOB** in the destination.

The resulting file passes everything:

```
integrity: ok        orphan pages: 0        search: 100 hits
```

…and is useless:

```
SOURCE:   typeof(source)=text   where source='telegram'  ->  326
REBUILT:  typeof(source)=blob   where source='telegram'  ->    0
```

Every byte present, every application query matching nothing. The app reads the
database as **empty**. Use a lossy decoder instead:

```python
src.text_factory = lambda b: b.decode("utf-8", errors="replace")
```

**Verification that catches it** (a green `integrity_check` never will) — assert
a type census plus one real application-shaped predicate:

```python
kinds = conn.execute(
    "select typeof(source), count(*) from sessions group by 1").fetchall()
assert all(k == "text" for k, _ in kinds), kinds
assert conn.execute(
    "select count(*) from sessions where source='telegram'").fetchone()[0] > 0
```

Mutation-test the guard: reintroduce `text_factory = bytes` and require the test
to FAIL.

## 5. "Missing rows" after a snapshot rebuild are usually newer rows

Post-rebuild diff looked alarming — `messages: MISSING 1678`,
`sessions: MISSING 4`. Both were wrong readings.

Diff by **primary key**, not by count:

```python
new_ids = {r[0] for r in dst.execute("select id from messages")}
missing = [i for (i,) in src.execute("select id from messages")
           if i not in new_ids]
```

Result: `missing ids found: 0`. Every apparent gap was above the snapshot's
high-water mark — rows the live service wrote _during_ the 100-second copy.
Confirm with `select count(*) from messages where id > <dst max id>`.

Counts drift under a live writer; identity sets do not. Report "zero rows were
unreadable", not "99.6% recovered", when the ids prove it.

## 6. A high-water mark is wrong for TEXT and composite primary keys

Delta-sync by `max(rowid)` works for `messages` (INTEGER pk). It is meaningless
for tables whose pk is TEXT or composite, because the rebuild renumbers rowids:

| table                 | primary key        | `max(rowid)` delta reported     |
| --------------------- | ------------------ | ------------------------------- |
| `sessions`            | `id` TEXT          | 1,344 "new" of 3,638 — nonsense |
| `system_prompts`      | `hash` TEXT        | crashed: `no such column: id`   |
| `session_model_usage` | 6-column composite | 2,150 "new" of 4,485            |

Inspect `pragma table_info` for the real pk. Use an incremental window only for
INTEGER-rowid tables; **full re-sync the rest with `INSERT OR REPLACE`** and let
the primary key resolve duplicates. Correct regardless of key shape, and cheap
at these row counts.

## 7. `Restart=always` defeats every offline window

`systemctl --user stop` is undone in `RestartUSec` (5s here). Symptoms: a repair
script aborts with "database is held", or worse, races a live writer.

- `systemctl mask` is **refused** when the unit is a real file rather than a
  symlink: `Failed to mask unit: File ... already exists`.
- The lever that works is a drop-in, removed on the way out:

```bash
DROPIN=$HOME/.config/systemd/user/$UNIT.d/zz-maintenance.conf
trap 'rm -f "$DROPIN"; rmdir "$(dirname "$DROPIN")" 2>/dev/null;
      systemctl --user daemon-reload;
      systemctl --user reset-failed "$UNIT";
      systemctl --user start "$UNIT"' EXIT
mkdir -p "$(dirname "$DROPIN")"
printf '[Service]\nRestart=no\n' > "$DROPIN"
systemctl --user daemon-reload
systemctl --user stop "$UNIT" || true
```

🔴 **Size the hold-down wait against the SLOWEST member, and poll unit state —
not a fixed timeout.** A 45-second `lsof` poll was enough on quiet profiles and
too short on the busiest one; the script hit `ABORT: still held`, `set -e`
unwound, and the `trap` restarted the service. Poll until
`systemctl is-active` reports `inactive`/`failed` **and** `lsof -t <db>` is
empty, with a multi-minute budget.

A related reporting trap: after the trap has fired, the gateway is legitimately
`active` and holding the file again. Reading that live state as "the drop-in
failed" is wrong — check whether the script already exited first. Print a line
per phase so a stall is visible rather than silent.

**A dry run that validates the sync PLAN does not validate the STOP sequence.**
Exercise the hold-down separately against the busiest target before relying on
it for an irreversible step.

## 8. Verify-then-swap, with the abort inside the script

Order that survives a live writer:

1. hold the service down, prove zero `lsof` holders
2. sync the delta (§6)
3. rebuild FTS over final data
4. **verify: integrity, type census, per-source counts ≥ live, search hits,
   and READABLE identity sets within a bounded tolerance (§11, §12)**
5. abort on any failed check — `sys.exit(1)` **before** any rename
6. `os.rename` the corrupt file aside, `os.rename` the new file in, `chmod 0600`
7. start, then prove the process ATTACHED (`lsof -p <pid> | grep state.db`)

Keep the corrupt original: the swap stays reversible. Note the rebuilt file may
be _larger_ mid-run (fresh B-trees, no free space) and settles smaller —
3003 MB → 2633 MB here.

## 9. The user-visible symptom is a safety net, not the disease

```
⚠️ No reply: the turn was stopped because session storage could not be
written (the transcript would have been lost on restart).
```

Source: `run_agent.py:3743`, reason `session_persistence_failed` with an unknown
cause. Hermes tried to persist the transcript, SQLite returned `malformed`, and
it **deliberately stopped the turn** rather than run work it could not record.

Consequences worth knowing before triaging:

- **Cron jobs fail first.** They create a NEW session, writing to `sessions`;
  interactive turns mostly append to existing rows and survive. So it presents
  as "the watchdog is broken", not "the database is broken".
- Hermes then **detaches FTS and keeps canonical writes alive**
  (`Automatic rebuild of stale FTS indexes failed …; canonical writes remain
enabled with FTS detached`), retrying every 5 minutes. Failed turns stop while
  the corruption remains — do not read that quiet as fixed.
- Also note `disk I/O error` in the app log against a clean `dmesg` is not a
  contradiction to hand-wave; see `recurrent-corruption-root-cause-triage.md`.

## 10. Attribute write pressure with a control population

Before accepting "it corrupts because it is busy", measure every peer. One
profile was the only corrupt database **and** the heaviest writer by 5.7x:

| profile                    | integrity | msgs/24h | job fires/day |
| -------------------------- | --------- | -------- | ------------- |
| a trading agent            | PROBLEM   | 103,710  | 3,086         |
| a research agent           | ok        | 18,130   | 1,800         |
| a personal-assistant agent | ok        | 13,556   | 1,065         |
| a personal-assistant agent | ok        | 8,875    | 62            |

The control population does real work here: a research agent fires nearly as many jobs
and is fine, so it is **write volume, not schedule density**.

Then decompose before proposing a fix — the intuitive culprit was wrong:

| source   | msgs/24h | share   |
| -------- | -------- | ------- |
| telegram | 96,985   | **93%** |
| cron     | 3,282    | 3%      |
| subagent | 2,974    | 3%      |

Not scheduled jobs at all. It concentrated in a few never-ending conversations
(45,682 messages in one 4.9-day session; 18,862 over 19 days), each turn
appending to a session already tens of thousands of rows deep with the trigram
index rewriting on every insert. Role mix was 33 machine messages per user
message.

That reframes the durable fix from "reduce job count" to "bound session
lifetime" — a target you only find by grouping, not by assuming.

## 11. `count(*)` on a corrupt B-tree reports PHANTOM rows

🔴 The single hardest trap in this whole procedure. A corrupt database can
report more rows than it can produce, because `count(*)` is answered from
B-tree bookkeeping that the damage has falsified:

```
live count(*):            455,522
live fully enumerable:    455,487
phantom (counted, never readable): 1,937
```

A verification gate written as `new_count >= live_count(*)` therefore **can
never pass** — it is holding the rebuild to a number that includes rows which
do not exist. Three consecutive swap attempts aborted on this, each looking
like real data loss (`messages SHORT (short 2035)`) and each prompting a
pointless deeper hunt for "missing" data.

Compare **readable identity sets**, not counts:

```python
def readable_ids(src, table, keycol):
    """Enumerate keys, degrading to row-by-row across corrupt pages."""
    try:
        return {r[0] for r in src.execute(f'select "{keycol}" from "{table}"')}
    except Exception:
        ids, lo, step = set(), 0, 5000
        top = src.execute(f'select max(rowid) from "{table}"').fetchone()[0] or 0
        while lo <= top:
            try:
                ids |= {r[0] for r in src.execute(
                    f'select "{keycol}" from "{table}" '
                    f'where rowid >= ? and rowid < ?', (lo, lo + step))}
            except Exception:
                for rid in range(lo, lo + step):
                    try:
                        r = src.execute(
                            f'select "{keycol}" from "{table}" where rowid=?',
                            (rid,)).fetchone()
                        if r:
                            ids.add(r[0])
                    except Exception:
                        pass
            lo += step
        return ids

missing = readable_ids(src, "messages", "id") - {
    r[0] for r in dst.execute("select id from messages")}
```

Report the reconciliation explicitly — "the live database counts N rows it
cannot produce" — so the deficit is never mistaken for loss you caused.

## 12. A zero-loss gate cannot pass against permanent damage

Rows behind corrupt pages are unrecoverable _by anything_. A gate demanding
`missing == 0` blocks the swap forever over data that is already gone, keeping
the service on the corrupt file indefinitely — the gate defeats its own purpose.

Use a small bounded tolerance, and **print exactly what is being abandoned**:

```python
tolerance = max(20, len(live_ids) // 20000)   # ~0.005%
checks[label] = len(missing) <= tolerance
if missing and len(missing) <= 10:
    print(f"    unrecoverable ids: {sorted(missing)}")
```

Final real loss here: **4 messages and 3 sessions**, all created inside the
corruption window itself, named by id in the log. That is a defensible number
to hand a user; "99.6% recovered" is not.

## 13. Every read against a damaged source needs a degrade path

A delta sync issued as one query over the corrupt region raised `malformed`
and yielded **0 of ~2,000 rows** — the whole table silently synced nothing,
and verification correctly refused the swap. The copy loop had per-row fallback
on _writes_ but not on _reads_.

Rule: in a rebuild, **every** read is chunk → sub-chunk → single row, counting
what is genuinely unreadable. Recursive bisection keeps the cost near-zero when
data is clean:

```python
def read_range(table, collist, key, lo, hi):
    try:
        return src.execute(
            f"select {collist} from {table} where {key} >= ? and {key} < ?",
            (lo, hi)).fetchall(), 0
    except Exception:
        if hi - lo <= 1:
            return [], 1                      # one genuinely bad row
        mid = (lo + hi) // 2
        a, ab = read_range(table, collist, key, lo, mid)
        b, bb = read_range(table, collist, key, mid, hi)
        return a + b, ab + bb
```

That change alone recovered 1,996 of the 2,000 rows the single-query version
lost.

## 14. Run catch-up and swap in ONE hold-down, and re-assert the invariant

Splitting "catch up the delta" and "swap" into two processes fails two ways:

- Rows written between the two steps make the swap look permanently short —
  it races the writer and can never converge.
- The catch-up process itself opens the live file. Its handle, or a systemd
  restart in the gap, leaves a holder and the swap's own `lsof` guard aborts
  the run: `ABORT: gateway still holds the database`.

Do the catch-up **inside the hold-down window**, then re-assert zero holders
immediately before the rename rather than aborting the whole run:

```bash
holders=$(lsof -t "$DB" 2>/dev/null | wc -l | tr -d ' ')
if [ "$holders" != "0" ]; then
  echo "  holder reappeared after catch-up; clearing"
  systemctl --user kill -s SIGKILL "$UNIT" 2>/dev/null || true
  for p in $(lsof -t "$DB" 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
  sleep 3
fi
```

## 15. SIGKILL is legitimate when you are replacing the file anyway

A graceful drain is protecting in-flight work that is about to be discarded.
The busiest profile drained for **195 seconds** ("Gateway drain timed out after
180.0s with 1 active agent(s), 2 in-flight cron job(s)") on every attempt,
making each iteration too slow to converge.

With the owner's approval, give the graceful path a short grace then kill —
**195s → 5s**, which is what made the last iterations tractable:

```bash
systemctl --user stop "$UNIT" &
sleep 25
if [ "$(lsof -t "$DB" 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; then
  systemctl --user kill -s SIGKILL "$UNIT" 2>/dev/null || true
  for p in $(lsof -t "$DB" 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
fi
```

Safe **only** in this specific shape: the delta is synced from the live file
_after_ the process is gone, so a killed writer cannot leave a torn row in the
destination. Do not generalize it to maintenance that keeps the existing file.

## 16. Iterate on a fixture, not on the production database

Six attempts were needed here, and the ones that burned a live hold-down window
were the ones tested only against production. The reliable loop is: reproduce
the exact broken state in a temp database, fix, mutation-test the guard, _then_
run against the real file. `scripts/rebuild_from_corrupt.py` ships with a
fixture harness that corrupts interior B-tree pages of a known table and
asserts recovery — 99% of rows, `integrity ok`, search working, types still
`text`.

The verification discipline that actually caught things, in order of value:

1. **Diff against the source**, never trust a green `integrity_check` alone —
   this is what caught the BLOB bug (§4) that would have shipped an
   app-empty database.
2. **Mutation-test each guard** — reintroduce the bug, require FAIL.
3. **Keep the abort inside the script**, so a failed check cannot reach the
   rename.

Every one of the six failures was caught by verification rather than shipped,
and the live database was never touched until all checks passed. That is the
property to preserve when adapting this procedure.
