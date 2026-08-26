# Immutable reads: warn on `-wal` presence, not on the fallback itself

Follow-on to `read-only-connect-lazy-failure.md`. That file explains why a
`?mode=ro` connect fails and why the fallback to `immutable=1` is necessary. This
file covers the mistake that comes _after_ you build the fallback: warning about it
unconditionally.

Learned 2026-08 rolling a diagnostic collector to 12 machines.

## The symptom

Every single agent — 12 of 12, independently — reported:

```
stale_immutable_reads: ['executions.db']
```

and then correctly refused to certify scheduler health, downgrading real conclusions
(`jobs_overdue_count: 0`, `jobs_stalled_no_later_completion: 0`) to "cannot
determine" and escalating to a human.

**Twelve independent agents reaching the same alarming conclusion is a bug in the
instrument, not twelve coincidences.** That inference is the reusable part.

## Root cause, reproduced deterministically

A WAL-mode database with **no `-wal`/`-shm` sidecars** cannot be opened with
`mode=ro` at all. Opening a WAL database requires creating a `-shm` sidecar, and
read-only mode forbids it:

```
sqlite3.OperationalError: unable to open database file
```

This is the _cleanly-closed, fully-checkpointed_ state — i.e. every idle database on
a normally-running host. So the collector fell back to `immutable=1` almost always,
then warned that its own read might be stale.

Minimal repro (the sidecar removal is the part people forget — without it you prove
nothing, because a normal open recreates them):

```python
con = sqlite3.connect(db)
con.execute("PRAGMA journal_mode=wal")
con.execute("CREATE TABLE t(x)")
con.execute("INSERT INTO t VALUES (1)")
con.commit()
con.close()

for suffix in ("-wal", "-shm"):          # force the checkpointed state
    Path(str(db) + suffix).unlink(missing_ok=True)

# now mode=ro raises OperationalError; immutable=1 succeeds AND is exact
```

## The correction

`immutable=1` ignores the `-wal` file. Whether that matters is entirely conditional:

| `-wal` present? | Meaning                                                                                | Warn?   |
| --------------- | -------------------------------------------------------------------------------------- | ------- |
| No              | Cleanly checkpointed. The main image **is** the whole database. The read is **exact**. | **No**  |
| Yes             | Committed pages live outside the main image. Conclusions really may be stale.          | **Yes** |

```python
if mode == "immutable":
    # Only a live -wal means there are committed pages outside the main image.
    if Path(str(path) + "-wal").exists():
        STALE_READS.append(Path(path).name)
```

## Why this is a monitoring bug, not a cosmetic one

The false caveat did not merely add noise. Every agent used it to _downgrade
otherwise-valid findings_ and escalate. A warning attached to an exact read teaches
the reader to discount that warning — so when a genuinely stale read appears, it gets
ignored. Crying wolf costs you the one case the warning exists for.

Verification that the fix landed: the same agent that had been escalating returned
`[SILENT]` on its next run, with `collectors_failed: 0`.

## Testing note

Do **not** assert `mode=ro` fails as an invariant. It varies with SQLite build and
filesystem, and asserting it makes the test fail for reasons unrelated to what it
guards. Test the **warning rule** (`-wal` present ⇒ warn) instead — that is the
actual contract.
