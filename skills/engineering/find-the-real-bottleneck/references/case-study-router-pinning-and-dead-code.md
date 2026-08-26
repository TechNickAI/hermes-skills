# Case study: pinning, dead-code schedulers, and live-DB mutation (the router)

Concrete worked examples of the SKILL.md phases, from a 2026-08-03 investigation
of a self-hosted LLM router. The _patterns_ generalize; the file/line references
are specific to that codebase (`the router` skill covers the product itself).

## Pattern A — a handful of events amplified 75x (Phase 4)

A ~$213/day spend spike looked like "lots of upstream errors causing failover."
Arithmetic said otherwise:

```
sessions pinned to the PAID model      : 6
paid calls those 6 produced            : 452  (105.4M tokens, ~$211/24h)
amplification                          : 75x per ignition
sessions pinned to the FREE rung-1     : 1,477
```

The routing ladder was working correctly on 1,477 sessions. The cost came from
**6 poisoned sessions welded to an expensive path**. Fix the amplifier, not the
trigger.

**Proof the ladder was bypassed rather than losing a race** — over one 2h window:

```
rung1 attempts: 299 · rung2: 6 · rung3: 0
rung3 COMPLETIONS in the same window: 270
```

Zero attempts with 270 completions ⇒ requests were rewritten _before_ the ladder
ran. Corollary: adding a cheaper intermediate rung would have changed nothing.

**Generalizable lesson:** when a caching/affinity layer pins a session to
whatever succeeded last, check whether its invalidation guards ask
_"is the pinned target reachable?"_ (they usually do) versus
_"has a better/cheaper target recovered?"_ (they usually don't). A pin to a
**healthy but expensive** target is permanent by design — the expensive provider
never fails, so nothing ever drops the pin.

Also worth checking before filing upstream: the system often **already computes
the cost data** it fails to consult (here, per-model pricing was computed for
target ordering and simply not read at pin time). That turns "feature request"
into "you have the data, you're not using it."

### Explaining a surprising design: read the guards' comments, not just the code

When the user keeps saying _"this doesn't make sense to me"_ / _"is this really
just a bug? seems so basic"_, restating the mechanism louder does not land. What
lands is **why a competent author would have built it this way**, which is
usually recorded in the guard's own comment, often naming the incident:

> "incident 2026-06-21: … pinned to a deepseek connection with no active
> credentials → instant fail, never falling through"
> "incident 2026-06-22: laila stuck on a throttled claude account …"

Reading those revealed both guards asked _"is the pinned target reachable?"_ —
neither asked _"has a better target recovered?"_ That reframes the finding from
"basic bug" to **a design gap with a coherent history**, and simultaneously
explains why most users never hit it (their fallback rung is free, so the pin
costs nothing).

Give the user the three-part answer explicitly:

1. **What is sound about the design** (cache locality is genuinely worth
   protecting when re-encoding a 240k-token conversation).
2. **What the real gap is** (guards test liveness, never priority/cost recovery;
   no TTL).
3. **What our own config contributed** (we put a paid model on a cache-protected
   combo — invisible to anyone whose fallback is free).

Answering only (2) reads as blaming upstream; answering only (3) reads as blaming
the user. Give all three.

## Pattern B — the feature exists, is called, and never runs (Phase 4b)

Retention cleanup was configured (`rawDataRetentionDays = 7`) yet tables held 15
days / 341,362 stale rows. The scheduler was correctly written _and_ correctly
invoked — from a module **nothing imports**. Upstream's own comments admitted it:

> "Previously this was only wired into the unused `server-init.ts`, so it never
> ran in production."
> "…that module is never imported anywhere (it is stranded/dead code)."

**Cheapest possible check — does the log line the feature MUST emit exist?**

```bash
journalctl --user -u <svc> --since "3 days ago" | grep -c "\[Cleanup\]"   # 0
```

A scheduler that logs unconditionally on every run, with zero lines ever, has
never executed. That is a one-command disproof of "it's configured, so it runs."

**Then check the deployed artifact, not the source tree:**

```bash
WD=$(systemctl --user show <svc> -p WorkingDirectory --value)
grep -rl "<a string the feature must contain>" "$WD"    # empty = not shipped
```

Source containing a fix proves nothing about the running bundle.

**Sibling-signal trick:** other jobs started on adjacent lines of the same init
function _were_ logging. That narrowed it from "init didn't run" to "this
specific module is unreachable" without a debugger.

## Pattern C — mutations that silently revert (Phase 4b)

Deleting rows from a DB held open by a live process: the delete committed, read
back as `0` in-connection, and was **fully restored seconds later**. Row counts
then climbed past the original.

Cause: the process holds a large SQLite page cache (`cacheSize: 65536` = 64 MB)
and treats its in-memory pages as authoritative; its next write flushes stale
pages over the external change.

**Decisive test that separates "process re-inserting" from "cache overwrite":**
delete rows the process _cannot_ be creating — dated two weeks ago.

```
Jul-20 rows: 22515 -> 0  (deleted 22515)
after 6s:    22515        <-- restored ⇒ overwrite, not re-insertion
```

`wal_checkpoint(TRUNCATE)` makes the change briefly visible — a red herring.

**Working procedure:** backup → stop service → mutate + VACUUM → start → verify
counts persist _after_ restart → run a real end-to-end request. Measured:
342,696 rows deleted, 521 MB → 358 MB, ~75s downtime, median endpoint latency
roughly halved.

**Escalate to stop-the-service after the SECOND failed attempt, not the fifth.**
The failure mode here is retrying cleverer variants of an approach that cannot
work: plain SQL → `better-sqlite3` → `wal_checkpoint(TRUNCATE)` → 10k-row chunked
loops. The chunked loop was the clearest tell — it counted 110k → 30k, then
**jumped back to 100k**, i.e. progress was being erased wholesale mid-run. Any
non-monotonic progress counter means something is reverting you; stop iterating
and take the lock. In this session the user had to say _"I suspect you're going
to have to stop the service"_ before that happened, which is a cheap correction
that should not have been needed.

Budget the downtime honestly and just ask: ~75–150s of router downtime is a far
smaller cost than an hour of mutations that silently evaporate.

**Verify column names and epoch units per table before a multi-table purge.**
A 12-table cleanup silently no-op'd on several tables because the schema is
inconsistent — same logical concept, different column and different unit:

```
usage_history, call_logs, proxy_logs      timestamp    ISO text
mcp_tool_audit, a2a_task_events           created_at   ISO text   (NOT timestamp)
xp_audit_log                              created_at   TEXT 'YYYY-MM-DD HH:MM:SS'
domain_cost_history                       timestamp    INTEGER epoch MILLIseconds
```

Passing an epoch-**seconds** cutoff to the milliseconds column deleted 0 rows and
reported success. Always print `before → after (deleted N)` per table; a table
reporting `deleted 0` when you expected thousands is a schema mismatch, not a
clean table. Confirm with `PRAGMA table_info(<t>)` plus `MIN()/MAX()` of the
column before trusting the result.

## Pattern D — schema changes that self-heal on boot

Before recommending "drop this index," find what the startup path executes.
`db.exec(SCHEMA_SQL)` on every boot, with `CREATE INDEX IF NOT EXISTS` inside,
means a drop reverts on the next restart.

- boot-path schema blob → recreated every start; needs a source edit + build
- numbered migration, tracked in a migrations table → applied once, forward-only

Watch for a decoy: a top-level `db/migrations/` may be empty while the live path
is `src/lib/db/migrations/`.

## Pattern E — transient torn reads ≠ corruption

Reads against the busy live DB intermittently threw
`SQLITE_CORRUPT: database disk image is malformed`, but `PRAGMA integrity_check`
on a `.backup` snapshot returned `ok`. Wrap live reads in a ~10-attempt retry
loop rather than "fixing" a healthy database. Report it as transient, and say so
plainly if it interfered with a measurement.
