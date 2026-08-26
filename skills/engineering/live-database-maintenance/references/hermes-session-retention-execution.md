# Reading retention results without scaring yourself

Companion to `silent-noop-retention-wrappers.md` (which covers wrappers that
delete nothing) and `chunked-retention-and-silent-weekly-jobs.md` (which covers
slicing and scheduling). This file is the smaller set of
**interpretation** traps: places where correct output looks like a bug, or a
bug looks like success. Measured 2026-08-22 across 14 Hermes profiles.

## An FTS recall drop is not automatically data loss

After pruning a 6.7 GB store, a sampled search term fell **300 → 182 hits**.
That reads like the prune ate user history. It had not: grouping the survivors
by source showed every lost hit lived in a deleted cron/subagent row, while
hits inside human sessions were untouched (23 / 75 / 271 for three terms).

```sql
SELECT COALESCE(s.source,'?') AS src, COUNT(*)
FROM messages_fts f
JOIN messages m ON m.id = f.rowid
JOIN sessions s ON s.id = m.session_id
WHERE messages_fts MATCH 'term'
GROUP BY src ORDER BY 2 DESC;
```

**Always group an FTS delta by source before calling it data loss**, and quote
the human-session number to the owner — that is the figure they actually care
about. A raw recall count mixes machine chatter into the same number and will
make a healthy run look destructive.

## Prune only takes ENDED sessions

A dry run reported 239 eligible cron sessions where the raw `sessions` table
showed 313. The gap is unended sessions, which prune deliberately skips. Expect
the discrepancy before anyone reconciles the two numbers by hand and concludes
the filter is broken.

## Deleting a lot of rows may free surprisingly little

On one profile, **8,447 sessions deleted freed 478 MB** on a file still 1.77 GB
afterwards. The remainder is overwhelmingly FTS index, not conversation text.

Say this plainly when reporting: retention **stops the growth**, it does not
shrink a store back to nothing. If the owner's actual goal is disk footprint,
the bigger lever is the FTS/trigram index (see the sizing section in SKILL.md),
and that is a search-quality tradeoff to be decided separately — not something
to slip into a retention change.

## Custom sources exist — allowlist, never denylist

One profile carried `lead-intake-processor` sessions alongside the usual
telegram/cli traffic. An allowlist of `("cron", "subagent")` protected it with
no special handling; a denylist of known-human sources would have deleted it
silently. Assume every fleet has at least one source you have never seen.

## Self-maintenance is allowed — the lifecycle guard does not apply

The Hermes lifecycle guard blocks a gateway **stopping or restarting itself**.
Retention is short transactions against a live store and stops nothing, so a
profile can maintain its own `state.db` from inside its own gateway. Verified
live on the agent's own database.

Do not design a central SSH-based runner to work around this constraint — it
does not exist for retention, and a central do-er is the wrong shape anyway
(per-agent jobs on their own hosts fail independently and are debuggable).

## Freshly registered cron jobs show a null next run

Immediately after writing a job entry, `next_run_at` is `None` and `cron list`
renders `Next run: None` or `?`. The scheduler fills it in on its next tick
(~60-90 s later). Re-read before concluding the registration failed.

Related display trap: `grep -A3` around a job name **bleeds into the following
job's fields**, so you can read a time that belongs to a different job. Verify
against the stored `schedule.expr`, not scraped console output.
