# Corruption discovered mid-plan: the stop rule

Companion to `references/corruption-recovery-and-merge-forward.md` (how to
recover) and `references/recurrent-corruption-root-cause-triage.md` (why it
keeps happening). This file covers the narrower, sharper moment: **you were
about to run maintenance, and the database turns out to be already damaged.**

## 🔴 The stop rule

**Never `VACUUM` a database that fails an integrity check.**

`VACUUM` rewrites the entire file. Running it against a database with a corrupt
page is how localized, survivable damage becomes total loss. `--keep-backup`
does **not** protect you here — the backup is a copy of the corruption, so you
would hold two damaged files and no good one.

The same applies to any whole-file rewrite: `VACUUM INTO`, a dump/reload, or an
"optimize" pass. Stop, localize, repair the specific damage, re-verify, and
only then consider compaction.

## How this surfaced (measured)

Measuring VACUUM cost on a copy (see
`references/vacuum-lock-budget-and-write-patience.md`) is what caught it. The
copy failed:

```
sqlite3.DatabaseError: database disk image is malformed
```

A `cp` of a live WAL database is a torn snapshot, so that alone proves nothing
— **always re-check the live file read-only before concluding anything.** Here
the live file failed too, which made it real:

```python
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
c.execute("pragma quick_check") # DatabaseError: malformed
c.execute("pragma integrity_check") # DatabaseError: malformed
```

Note the service was **still running and serving normally**. SQLite only faults
when it touches the damaged pages, so a corrupt database can look completely
healthy from the outside for a long time.

## Localize before you panic (and before you repair)

An integrity failure is not automatically a lost database. Walk every table and
find out what is actually damaged:

```python
tables = [r[0] for r in c.execute(
    "select name from sqlite_master where type='table' order by name").fetchall()]
for t in tables:
    try:
        c.execute(f'select count(*) from "{t}"').fetchone()
        print("ok ", t)
    except Exception as e:
        print("BAD ", t, str(e)[:70])
```

Also probe FTS with a real `MATCH`, not just a count — an FTS index can pass a
row count and still throw on query.

Measured result on the affected trading-bot store: **one table** was damaged.

| table                                   | state                                    |
| --------------------------------------- | ---------------------------------------- |
| `sessions` (3,629 rows)                 | ok                                       |
| `messages` (452,404 rows)               | ok                                       |
| `messages_fts`, `_trigram`, all shadows | ok, `MATCH` works                        |
| every other table                       | ok                                       |
| **`delivery_obligations`**              | **malformed** — even `max(rowid)` throws |

That distinction decides everything:

- **Rebuildable tables** — FTS shadow tables, and operational queues like
  `delivery_obligations` (a pending-outbound-message queue: `obligation_id`,
  `session_key`, `platform`, `chat_id`, `content`, `state`, `attempts`).
  Losing these costs pending work, not history. Drop and recreate.
- **Irreplaceable tables** — `sessions`, `messages`. These need the
  merge-forward recovery in
  `references/corruption-recovery-and-merge-forward.md`.

Report which of the two you are in **before** proposing a fix. "One queue table
is damaged, all 452k messages are intact" is a very different conversation from
"the database is corrupt".

## Do not claim your own earlier work is unrelated

An earlier retention run on the same database had completed cleanly, with
verified counts and `integrity_check: ok` afterwards. That makes it _unlikely_
to be the cause — but the honest statement is that the corruption appeared
sometime after, and the sequence is not proven either way.

Say that plainly rather than asserting innocence. Volunteering the uncertainty
is what makes the rest of the report trustworthy, and the owner can weigh it.

## Ordering for the repair

1. Back up the damaged file **as-is** (you may need it to salvage rows later).
2. Recreate only the damaged rebuildable table.
3. Re-run the **full** `integrity_check` — not `quick_check`.
4. Only after a clean check, reconsider compaction.

A schema-level write to a live production database — especially one on a money
path — is an approval gate. Present the localization, the proposed sequence,
and the cost of the lost rows, then wait.

## 🔴 The post-repair false all-clear

Step 3 is where a repair gets reported as cleaner than it is. Both of these
produce a confident, wrong "integrity_check: ok":

- **`quick_check` skips page-allocation analysis.** It returns a bare `ok` on a
  database that `integrity_check` reports orphaned pages for. It is not a
  cheaper synonym — it answers a narrower question.
- **`integrity_check` truncates its output** (100 messages by default), and a
  script that prints `rows[:3]` truncates it again. Slicing the result to keep
  the log tidy is how a real finding disappears.

Measured: a repair reported `quick_check: ok` and `integrity_check: [('ok',)]`,
and a later fleet-wide sweep on the same file surfaced:

```
*** in database main ***
Page 341812: never used
```

Read the whole result and count the categories explicitly:

```python
rows = [r[0] for r in c.execute("pragma integrity_check(100000)").fetchall()]
never = [m for m in rows if "never used" in m]
other = [m for m in rows if "never used" not in m and m != "ok"
         and not m.startswith("*** in database")]
print(f"orphaned pages: {len(never)} other problems: {other or 'NONE'}")
```

**`never used` pages are leaked space, not data damage** — allocated in the
file, belonging to no table, absent from the freelist. `VACUUM` is what
reclaims them, since it rebuilds page allocation from scratch. Distinguish them
from real damage before escalating: one orphaned 4 KB page on an otherwise
clean file is a footnote, not a corruption event.

The reporting rule: after declaring a database repaired, re-verify with the
full unsliced check and correct yourself out loud if it disagrees with what you
already said. A repair that is 99% clean should be reported as 99% clean.
