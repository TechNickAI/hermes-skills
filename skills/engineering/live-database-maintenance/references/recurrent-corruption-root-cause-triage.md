# Recurrent corruption: root-cause triage, not another repair

Use this when a database has corrupted **more than once** and the ask is "why
does this keep happening / what is the long-term fix", not "recover this file".
The sibling references cover recovery. This one covers _diagnosis of the
recurrence_ and the design answer.

Worked case: a Hermes `state.db` at 2.8 GB / 470k messages on a high-traffic
agent host, corrupting repeatedly over weeks.

---

## Rule 0 — check whether a repair is ALREADY IN FLIGHT before you touch anything

On arrival the live DB was throwing `file is not a database`. Before planning
anything, a directory listing found another operator/agent mid-recovery:

```
~/dbfix/ → snap.db, rebuilt.db, clean.db, phase1.log, phase3.log,
             final2.log, <profile>_go.sh (mtimes: MINUTES old)
ps aux → python -c "...connect('file:~/dbfix/clean.db?mode=ro')...
                        pragma integrity_check" (running RIGHT NOW)
```

Two writers racing a 2.8 GB rebuild is a lost-update disaster. The correct move
was to **read their logs and their swap script, wait for it to finish, then
verify their result** — not to start a parallel recovery.

Tells that a repair is in flight:

- a scratch dir (`dbfix/`, `recovery/`, `*.rebuilt`) with mtimes in minutes
- `.corrupt-<timestamp>` / `.bak-<timestamp>` siblings next to the live DB
- a live `integrity_check` / `.recover` / `VACUUM INTO` process in `ps`
- a hand-written swap script sitting next to the artifacts

Verification beats authorship. Same rule as concurrent memory-file rewrites:
never re-apply your own older snapshot over someone's finished newer result.

---

## Rule 1 — "are we on the latest SQLite?" is usually a dead end, but CHECK it first anyway

It is the user's first question and it deserves a real answer, because there IS
one library bug that matters:

- **`walresetbug`** — multi-process WAL corruption, fixed in **3.51.3**
  (backports 3.50.7, 3.44.6). Hermes' own `hermes_state.py` comments cite it
  and will refuse to _enable_ WAL on vulnerable builds.

Measure the version the **application** uses, not the system CLI — they differ:

```python
python -c "import sqlite3,sys; print(sys.version.split()[0], sqlite3.sqlite_version)"
```

Here: system `sqlite3` CLI was 3.45.1 while the venv Python linked **3.53.1** —
past the fix. So the library was ruled out, honestly and quickly, and the
investigation moved to the real causes. Do not skip this step; do not stop at it.

---

## Rule 2 — enumerate causes by EVIDENCE COUNT from the logs, not by plausibility

Grep the service's own error log and count. The ranking that falls out is the
diagnosis:

```bash
grep -ci "disk I/O error\|database or disk is full\|no space" logs/errors.log
grep -ci "malformed\|not a database\|corrupt" logs/errors.log
```

Measured here: **174 `disk I/O error`** occurrences preceding the malformed
errors. That ordering matters enormously — it reframes the whole problem.

> **Corruption downstream of `disk I/O error` is a SYMPTOM of the disk filling,
> not a random SQLite fault.** Fix the space, and the corruption class goes with
> it. Chasing SQLite tuning first solves nothing.

---

## The three real causes found (generalizable)

### A. Unbounded WAL → disk exhaustion → I/O errors → corruption

`PRAGMA journal_size_limit` defaults to **-1 (unlimited)**. After a checkpoint
the WAL is reused in place and **never truncated**, so it permanently retains
the high-water mark of the largest transaction ever run. One `VACUUM` or FTS
merge rewrites every page through the WAL.

Observed directly: WAL reached **1.5 GB in 20 seconds** during a journal-mode
conversion on a 2.8 GB DB. Hermes' own source documents the same failure filling
a host from 6.9 GB free to 772 MB and staying there.

Fix: set an explicit `journal_size_limit` (Hermes uses 64 MiB) so space returns
to the OS after big transactions.

### B. FTS5 triggers commit inside the same transaction as every row insert

FTS shadow tables are updated by trigger as part of the `INSERT INTO messages`
transaction. Interrupt that commit — SIGKILL, checkpoint failure, power loss,
full disk — and the base table and FTS index desync into "malformed".

This also makes FTS the **largest and most fragile object** in the file. Measured
composition of the 2.8 GB:

| object                      | size        |
| --------------------------- | ----------- |
| `messages` (data)           | 1254 MB     |
| `messages_fts_trigram_data` | **1101 MB** |
| `messages_fts_data`         | 349 MB      |
| all indexes on `messages`   | ~69 MB      |

The trigram index was **40% of the database** — nearly as large as the data it
indexes. Dropping trigram (or `detail=none`) reclaims that with **zero data
loss**, because external-content FTS5 rebuilds from the base table.

### C. An external "read-only" CLI process doing WAL maintenance on a live DB

A long-running `dashboard` process had been attached to the busy profile's DB
for **7 days**. Upstream reports the exact pattern: a health-check/CLI preflight
performs WAL checkpointing on a database another process is actively writing —
4 corruptions in 4 days on a busy host, **zero recurrence** once external CLI
access to the live DB was banned. A vanilla-SQLite control doing the same
concurrent-checkpoint pattern does _not_ corrupt, so this is application
behaviour, not a SQLite bug. Write pressure widens the race window, which is why
only the busiest host in a fleet sees it.

Count the attached writers before theorizing:

```bash
lsof /path/state.db | tail -n +2 | awk '{print $1,$2}' | sort -u
```

**The cheapest durable win in the whole investigation was "stop running a
dashboard against the live production DB."**

#### C2. 🔴 The agent SPAWNS its own second writer — read the fd MODE, not just the PID list

A second, independently-measured instance of cause C, and the sharpest one:
the corrupting process was **a child of the gateway itself**.

A bare `lsof` PID list is not enough, because a read-only attachment is
harmless and a read/write one is fatal. `lsof -F` exposes the access mode —
`r` = read, `u` = read/**write**:

```bash
lsof -F pcfan /path/state.db
# tag p=pid c=command f=fd a=access-mode
```

Measured on the corrupting host:

```
pid=2788769 cmd=hermes fd=33 mode=u GATEWAY
pid=2795631 cmd=hermes fd=6 mode=u *** NON-GATEWAY WRITER ***
```

The parent chain is what indicts the mechanism:

```
2795602 ppid 2788769 bash -lic... for M in gemini grok...
2795628 ppid 2795602 hermes -z "Review PRODUCTION CODE..."
```

**The gateway spawned a shell, which spawned a headless one-shot, which opened the
gateway's own `state.db` read-write.** Any agent workflow that shells out to
the same CLI — multi-model code review, a delegated `-z` one-shot, a self-check
that invokes `hermes` — becomes a second OS-level writer on a WAL database its
own parent is actively writing. Two processes each with their own lock state
and their own view of the WAL index is the textbook corruption path, and **no
pragma prevents it**: WAL's guarantees assume a shared locking protocol.

This also explains the fleet distribution cleanly — only the agent that spawns
a headless one-shot against itself corrupts, while busier peers stay clean. It is the
better explanation than raw write volume, and it is _testable in one command_,
so run the fd-mode check **before** building the volume/control-population
analysis in Rule 10.

Confirm the rest of the stack is innocent before blaming it, and say so:

- `is_sqlite_wal_reset_vulnerable()` → False on 3.53.1 (library ruled out)
- `synchronous=FULL`, `journal_mode=wal`, `busy_timeout=5000` (settings correct)
- zero kernel I/O errors in `dmesg`, filesystem `clean` (hardware innocent)
- Hermes' internal model is already safe: one lock-protected writer plus a
  bounded read-only pool with `check_same_thread=False`. The gap is _process_
  concurrency it cannot see.

Search upstream too — this class is reported by others (a closed macOS btree
issue, community reports of repeated `state.db` corruption), and the shipped
mitigations may be platform-gated (the macOS `synchronous=FULL` /
`fullfsync=ON` enforcement does nothing for the multi-process case on Linux).
Worth filing when the evidence is this clean.

**Fix direction:** stop the spawned CLI from writing the gateway's session
store — give it its own store or run it headless. That is a change to the
owner's workflow, so it goes through review, not a host edit.

---

## Rule 3 — measure WHICH writer produces the bytes; the obvious suspect is often wrong

The stated hypothesis was "too many cron jobs" (61 jobs, ~35 enabled, several at
`* * * * *`). Measurement partly falsified it:

| source × role        | rows    | MB        |
| -------------------- | ------- | --------- |
| telegram × tool      | 180,524 | **232.2** |
| cron × tool          | 32,734  | 186.5     |
| subagent × tool      | 17,644  | 128.2     |
| cli × tool           | 10,360  | 50.7      |
| telegram × assistant | 174,777 | 44.5      |

Cron was **not** the dominant byte producer — interactive traffic was. What the
job count actually contributes is **concurrency and churn** (more processes,
more transactions, wider race windows), which is a real but different problem
with a different fix.

By tool, the bulk is unsurprising once measured:

| tool           | rows    | MB    | avg         |
| -------------- | ------- | ----- | ----------- |
| `read_file`    | 31,398  | 178.5 | 5.8 KB      |
| `terminal`     | 126,439 | 152.2 | 1.2 KB      |
| `skill_view`   | 7,701   | 119.6 | **15.9 KB** |
| `search_files` | 17,927  | 57.1  | 3.3 KB      |

`role='tool'` totalled **611 MB of 725 MB** of all message text. The lever is
**truncating stored tool output**, not deleting conversations — and it does not
trip the orphaned-tool-call hazard, since you rewrite content rather than delete
rows.

Query shape:

```sql
select s.source, m.role, count(*), round(sum(length(m.content))/1048576.0,1) mb
from messages m join sessions s on s.id = m.session_id
group by s.source, m.role order by mb desc;
```

⚠️ Hermes `messages.timestamp` is an **epoch string**, not ISO. `substr(timestamp,1,10)`
silently returns a 10-digit epoch prefix and produces a nonsense "per day"
grouping that looks plausible. Check `typeof`/a sample value before grouping by
date. There is no `created_at` column on `messages`.

---

## Rule 4 — answer "can we move to Postgres?" by measuring coupling, not by opinion

The instinct to escape SQLite is reasonable and deserves a real check rather
than a reflexive no. Measure, in this order:

1. **Driver present?** `grep -i "postgres\|psycopg\|asyncpg\|sqlalchemy" pyproject.toml`
2. **Abstraction layer, or raw calls?** `grep -rln "sqlite3.connect" <src>` — count the modules.
3. **SQLite-only features in the schema?** FTS5 virtual tables, shadow tables,
   `dbstat`, triggers into FTS. These have **no Postgres equivalent** and each
   one is a rewrite, not a port.

Here: no driver, no ORM, raw `sqlite3` across ~40 modules, FTS5 virtual tables
throughout. That makes it a fork-level rewrite — a fair, evidence-backed "not
this path", stated with the measurements that support it rather than as a flat
refusal. **Re-measure rather than quoting this verdict**; a project can add a
backend at any time.

The honest framing for the user: the corruption is caused by disk exhaustion,
in-transaction FTS triggers, and an external writer. **Postgres would fix none
of those three by itself** — a full disk and a concurrent maintenance process
break Postgres too. Migration is not the lever the symptoms point at.

---

## Rule 5 — a DELETE→WAL conversion produces a terrifying transient WAL spike

After swapping in a rebuilt DB, `journal_mode` came back as `delete`
(rebuild artifacts commonly land this way). On first open the application
converted it to WAL, and the WAL went **0 → 751 MB → 1.5 GB in ~3 minutes**,
then settled to **1.1 MB** once checkpointing caught up.

Do not panic-intervene during that window, and do not report it as a leak.
Sample the size twice, ~20 s apart, before drawing any conclusion. Confirm the
end state:

```python
conn.execute("pragma journal_mode").fetchone() # -> ('wal',)
```

Deleting a `-wal` mid-conversion while a process holds the DB is how a scary
graph becomes real data loss.

---

## Rule 6 — verify the other side's repair on its own terms, then bound the residue

After the in-flight swap completed, the honest verification set was:

- `integrity_check` → `ok` (from a normal connection, per the read-only pitfall)
- row counts vs. the rebuild log (4,887 sessions / 470,173 messages — matched)
- **timestamp-gated** error count: every remaining `not a database` line was
  from _before_ the swap. Grep alone would have reported "still 9 errors!" and
  falsely condemned a good repair.
- named, quantified loss: 66 message rows, 3 routing rows, 2 system prompts
- rollback preserved: `state.db.corrupt-<stamp>` still on disk

Report the residue as a number. "Recovered successfully" without a loss count is
not a verification.

---

## Rule 7 — you cannot repair FTS under a supervisor that restarts the service

Offline repair means _the writer stays down for the whole repair_. Two levers
fail before you find the one that works:

1. `systemctl --user stop` alone — undone in 5 seconds by
   `Restart=always` / `RestartUSec=5s`. The repair then aborts with the
   database held open, and it is not obvious why.
2. `systemctl --user mask` — **refused** when the unit is a real file rather
   than a symlink: `Failed to mask unit: File ~/.config/systemd/user/<unit>
already exists.`

The lever that works is a drop-in that disables the restart policy, removed
again on the way out via a `trap`:

```bash
DROPIN=$HOME/.config/systemd/user/$UNIT.d/zz-maintenance.conf
cleanup() { # runs on EVERY exit path, including abort
  rm -f "$DROPIN"; rmdir "$(dirname "$DROPIN")" 2>/dev/null || true
  systemctl --user daemon-reload
  systemctl --user reset-failed "$UNIT" 2>/dev/null || true
  systemctl --user start "$UNIT" 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$(dirname "$DROPIN")"
printf '[Service]\nRestart=no\n' > "$DROPIN"
systemctl --user daemon-reload
systemctl --user stop "$UNIT" || true
for i in $(seq 1 45); do # poll for release, do not sleep
  [ "$(lsof -t "$DB" 2>/dev/null | wc -l | tr -d ' ')" = "0" ] && break; sleep 1
done
```

Verify by `lsof` count, not by unit state. A unit reporting `failed` after
SIGTERM is normal here and does **not** mean the file is released.

## Rule 8 — the fts5 repair ladder, and how to skip its two dead rungs

Repairing a corrupt external-content FTS index has an order that is not
obvious, and getting it wrong makes things strictly worse:

- **`INSERT INTO fts(fts) VALUES('rebuild')` FAILS on a corrupt index.** The
  rebuild still has to read the existing index structure. `database disk image
is malformed`.
- **`DROP TABLE messages_fts` also FAILS**, for the same reason — dropping an
  fts5 virtual table requires _constructing_ it first.

🔴 **Do not then delete the shadow tables anyway.** Doing that leaves the
virtual tables registered in `sqlite_master` but unconstructable, and the
database degrades from "search broken" to `vtable constructor failed:
messages_fts` on _every_ access — `pragma integrity_check` included, so you
lose your main diagnostic. Self-inflicted here.

The escape hatch is to remove the fts5 entries from the schema directly, then
recreate from the base table:

```python
conn.execute("PRAGMA writable_schema=ON")
conn.execute("DELETE FROM sqlite_master WHERE name LIKE 'messages_fts%'")
conn.commit()
conn.execute("PRAGMA writable_schema=OFF")
conn.close() # MUST reopen: the schema cache is stale
```

Then recreate — **views before the indexes that read them**. An
external-content FTS resolves its `content=` source at CREATE time, so
`messages_fts_trigram_src` must exist before `messages_fts_trigram`. A skip
list keyed on the `messages_fts` prefix will wrongly exclude that view; carve
it out explicitly.

With every FTS object removed, `integrity_check` returned **NONE** while
rebuilding immediately reproduced `malformed` — which is what localized the
damage to the base table rather than the index, and is the single most useful
diagnostic move in this whole class.

## Rule 9 — map the user-visible symptom to the code path before theorizing

The owner reports a job failure, not a database fault:

```
Cron 'open-pr-watchdog' failed: No reply: the turn was stopped because
session storage could not be written (the transcript would have been lost
on restart). Check the state database health (`hermes doctor`)
```

That string is `run_agent.py` (~3743) on `session_persistence_failed` with an
unknown cause. It is Hermes **deliberately refusing to continue a turn it
cannot persist** — correct behavior, and one layer removed from the disease.

Why it hits _cron_ jobs specifically: a cron run creates a **new session**, so
it writes to `sessions`; interactive messages mostly append to an existing one.
When the damaged tree is `sessions`, scheduled jobs fail while chat looks fine,
and the report arrives as "the watchdog is broken."

Related: a recurring
`Automatic rebuild of stale FTS indexes failed (...); canonical writes remain
enabled with FTS detached` every ~5 minutes is graceful degradation, not the
fault — Hermes detached the broken index to keep writes alive. It explains why
turn failures stop while corruption persists, and it means the service has been
walking the corrupt pages on a timer for hours.

## Rule 10 — a volume hypothesis needs a CONTROL POPULATION

"It corrupts because it is busy" is testable across a fleet, and the control is
what makes the answer trustworthy:

| profile             | integrity   | msgs/24h    | job fires/day |
| ------------------- | ----------- | ----------- | ------------- |
| **the corrupt one** | **PROBLEM** | **103,710** | **3,086**     |
| next busiest        | ok          | 18,130      | **1,800**     |
| others (12)         | ok          | < 13,600    | —             |

The one corrupt database was writing **5.7x** the runner-up. But the control
also refined the conclusion: a peer firing 1,800 jobs/day was healthy, so it is
write **volume**, not schedule density.

Then measure _which_ writer, because the intuitive answer was wrong again:

| source   | msgs/24h | share   |
| -------- | -------- | ------- |
| telegram | 96,985   | **93%** |
| cron     | 3,282    | 3%      |
| subagent | 2,974    | 3%      |

Cron was 3%. The pressure came from a few **never-ending sessions** — one with
45,682 messages over 4.9 continuous days, others at 18,862 and 13,522 running
19 and 18 days — at ~33 machine messages per human message. Each turn appends
to a session already holding tens of thousands of rows while the trigram index
rewrites on insert.

That points the durable fix at **bounding runaway sessions**, which no amount
of cron tuning would have reached.

## Rule 11 — "this keeps happening, we need a permanent fix" is a REDIRECT, obey it

Owner escalations in this class arrive as impatience with the repair loop:

> _"This keeps happening, we need a permanent fix!"_
> _"Fix the corruption. And we need to fix this more permanently."_

That is not a request to repair faster. It means the repair-verify-repair cycle
has itself become the problem, and the owner wants the _cause_ addressed. Two
concrete behaviours follow:

- **Stop repairing the symptom the moment a second instance appears.** Repairing
  one table at 12:05 and finding four different tables damaged by 13:45 is not
  "corruption spreading" — it is proof you are treating symptoms. Escalate to
  the base-table falsifier (Rule 8) instead of running the same repair again.
- **Do not let the fix land without the prevention.** When the rebuild
  succeeds, say plainly that it fixes _today_ and name the durable lever with
  its measurement. Here: 93% telegram traffic, one 45,682-message session
  running 4.9 days. A clean database handed back without that framing invites
  the identical incident next week.

Corollary on offering the owner harder levers: they may authorize things you
would not reach for unprompted ("you can kill it more aggressively if you need
to", "you can shut down X"). Take the offer when it is genuinely safe for the
operation at hand — a 195s graceful drain became a 5s SIGKILL and that is what
made the procedure converge — but state _why_ it is safe in this specific
shape, and do not carry the shortcut into operations where it is not.

## Rule 12 — do not declare a corrupt database fixed on a partial check

Three false all-clears were reported to the owner in a single session, each
from a check that was true-but-insufficient:

1. **`quick_check: ok` after repairing one table.** `quick_check` skips
   page-allocation analysis, so it passed while real damage remained.
2. **`integrity_check` read truncated.** The repair script printed only the
   first 3 rows of output; the full `integrity_check(100000)` carried the
   B-tree errors. Always read it unsliced.
3. **"one orphan page, no bad tables"** — a fleet sweep whose header already
   said `*** in database main ***`, skimmed as benign.

Worse, when a later probe returned `malformed`, the reflex was _"my nested
ssh/python quoting must be mangling the SQL."_ It was not — the database was
genuinely corrupt. 🔴 **When a probe reports corruption, do not blame your own
tooling.** Re-run it from a FILE on the host (never an inline `python -c`
through nested shell quoting, which does corrupt SQL and produces misleading
errors) and believe the answer.

The honest reporting shape when a repair lands:

- name what was verified and what was **not**
- state the residual loss as an exact number with ids, not a percentage
- say plainly that the repair fixes _today_ and name the unproven cause

Owners in this class are patient about a hard problem and unforgiving about a
premature all-clear. "Still corrupt, here is the evidence" costs nothing;
"fixed" that reverses in an hour spends trust that the actual fix will need.

1. **Remove external processes attached to the live DB** (dashboards, CLI health
   checks). No downtime, immediately reversible, highest evidence.
2. **Bound the WAL** — explicit `journal_size_limit`. Stops the disk-full →
   I/O-error → corruption chain at its source.
3. **Drop the trigram index** on hosts that don't need substring search. Largest
   single object, most corruption-prone, zero data loss to rebuild.
4. **Truncate stored tool output** at a cap (e.g. 32 KB). Where the bytes
   actually are; avoids row deletion and the orphaned-tool-call hazard entirely.
5. **Demote mechanical scheduled jobs to plain scripts.** A watchdog comparing a
   number does not need an LLM session or a transcript. Cuts concurrency and
   churn, which is what a large job count really costs you.
6. **Bound runaway sessions** on hosts where a few never-ending conversations
   dominate the writes (Rule 10). Measured shape: 93% of traffic from telegram,
   one session at 45,682 messages over 4.9 continuous days, two more running
   18-19 days. Every turn appends to a session already tens of thousands of rows
   deep while the trigram index rewrites on insert. Find them with:

   ```sql
   select s.id, s.source, count(*) n from messages m
     join sessions s on s.id = m.session_id
    group by 1,2 order by n desc limit 15;
   ```

   Ask the owner what the top session actually _is_ before capping it — a
   legitimate long-running loop needs a session boundary, not deletion.

7. **Stop the service from spawning a second writer against its own store**
   (C2 above). Highest evidence when `lsof -F` shows a non-gateway `u` holder
   descended from the gateway; requires a workflow change, so route it through
   the owner rather than editing the host.
8. **Nightly `quick_check` with alerting**, so corruption is discovered by a
   monitor rather than by a broken agent hours later.

Steps 3–7 are lossy or hard to reverse. Present 1–2 as the immediate action and
**gate the rest on the owner's decision** — especially removing a dashboard
something might depend on, and dropping an index that is expensive to rebuild.

One inventory note worth checking while you are on the box: confirm the
database actually sits on the volume intended for it. A host provisioned with a
dedicated state volume can still have `state.db` on the root disk — not a cause
of corruption, but wrong, and cheap to notice during triage.
