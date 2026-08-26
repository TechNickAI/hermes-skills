# When your "easy win" is already in place (or was never the problem)

Measured on a 2.8 GB Hermes `state.db` (a trading agent) after a real
corruption. Two fixes were proposed to the user with confidence. **Both were
wrong**, and each failed in a different, generalizable way. Verifying them took
about two minutes; proposing them cost credibility.

This is the failure mode where a _deep dive_ produces plausible remediation that
a _one-command check_ would have killed. Run the check before the sentence.

---

## Failure 1 — reading a connection-scoped PRAGMA from the wrong connection

**The claim:** "`journal_size_limit` is -1 (unlimited), so a single VACUUM can
strand a multi-GB WAL and fill the disk."

**The evidence I used:**

```python
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
c.execute("pragma journal_size_limit").fetchone()   # (-1,)
```

**Why it was wrong:** `journal_size_limit`, `cache_size`, `busy_timeout`,
`synchronous` and friends are **per-connection**, applied by the owning
application at connect time. A separate diagnostic connection never runs the
app's setup path, so it reports _its own_ defaults — not the writer's state.

The application in fact set it, at `hermes_state.py:806`:

```python
conn.execute(f"PRAGMA journal_size_limit={_WAL_SIZE_LIMIT_BYTES}")  # 64 MiB
```

**The falsifier, in order of strength:**

1. **Watch the artifact.** The live WAL grew during a heavy write burst and
   stopped at exactly `67108864` bytes — 64 MiB on the nose. A round number
   matching a source constant is proof the setting is live.
2. **Grep the source for the pragma name.** If the app sets it, your connection's
   reading is irrelevant.
3. Read `/proc/<pid>/fd` or `lsof -p <pid>` to confirm which files the _writer_
   holds.

**Rule:** never report a pragma value as a property of _the database_ unless it
is one of the genuinely persistent ones (`journal_mode`, `page_size`,
`auto_vacuum`, `application_id`, `user_version`). Everything else is a property
of _a connection_. To characterize the writer, read the writer's source or
observe its artifacts.

---

## Failure 2 — inferring a mechanism from a process name

**The claim:** "A long-running `dashboard` process has been open against this
profile since Aug 14; upstream documents 'read-only' CLI health checks doing WAL
maintenance on a live DB and causing repeated corruption. Kill it."

The cited upstream issue was real and the mechanism was real. The inference was
not: **I never checked whether that process had the database open.**

**The falsifier, one command:**

```bash
ls -l /proc/<pid>/fd | grep -i '\.db'      # dashboard: zero matches
lsof -p <pid> | grep state.db              # zero matches
```

For contrast, the actual writer:

```
11 /home/.../profiles/a trading agent/state.db
 6 /home/.../profiles/a trading agent/state.db-wal
 1 /home/.../profiles/a trading agent/state.db-shm
```

The dashboard held **no** database handles. It was never a participant.

**Rule:** a process name plus a matching upstream issue is a _hypothesis_. File
descriptors are the evidence. Before recommending that anything be killed,
restarted, or removed, prove it touches the resource — and prefer the cheap
proof over the compelling narrative. A well-matched upstream issue makes this
error _more_ likely, not less, because the story feels already-confirmed.

---

## The general check: is it already fixed?

Both failures share one root: proposing remediation without asking whether the
system already does this.

Before presenting any fix, run the three-line audit:

```bash
# 1. Does the app already set it?
grep -rn "<pragma_or_setting>" <app_source> | grep -v test

# 2. Does the artifact show it working?
ls -la <db>-wal        # capped at a round number == limit is live

# 3. Is there already a disabled/paused mechanism for this?
grep -i "prune\|vacuum\|retention\|hygiene" <profile>/cron/jobs.json
```

Step 3 found the real answer in this session (below).

---

## What the real finding turned out to be

Not a missing setting. A **working mechanism that had been switched off.**

A well-built weekly pruner existed — disk-headroom guard before VACUUM, 14-day
retention on cron/subagent only, explicitly never touching human conversations,
silent unless it reclaimed something. It was `enabled: false`, with
`paused_at` timestamped **during the previous day's corruption firefight**. It
had never been switched back on. That is exactly why ~150 MB of dead cron
sessions had accumulated.

**Rule — post-incident disable audit.** After any firefight, enumerate what was
paused, disabled, commented out, or masked during the response, and confirm each
one was restored. Grep for `paused_at` / `enabled: false` with a timestamp near
the incident window. A safety mechanism disabled during an incident and never
re-enabled is a _scheduled recurrence of that incident_.

When you find one, prefer re-enabling the existing job over writing a new one:
it already encodes headroom guards and scope limits that a fresh script will
omit. Back up `cron/jobs.json` first and read the job definition back to confirm
`enabled`, `state`, and schedule.

---

## Reporting shape when your own proposals collapse

Both proposals died under verification _after_ being presented. The correct
response is to lead the report with the corrections, plainly, before describing
what was accomplished:

> Two things I told you earlier turned out to be wrong. The dashboard was a
> false lead — it holds zero `.db` files open [...] `journal_size_limit` is
> already set; I read it off my own read-only connection, which never runs the
> setup path.

Do not bury a retracted claim under a successful outcome, and do not quietly
drop it. Name the wrong claim, name the measurement error that produced it, and
state the evidence that overturned it. The user calibrates on whether you catch
your own errors out loud.
