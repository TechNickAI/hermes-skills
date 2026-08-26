# Recovering a corrupt SQLite database by restore + merge-forward

Use when a live database reports `database disk image is malformed` and the goal
is to get the service healthy again **without losing the writes made since the
last backup**. This is the repair path; the rest of the skill covers routine
maintenance on a healthy database.

## 0. Do not trust the user-facing error text

Hermes surfaces session-write failure to the user as:

> "session storage could not be written (the transcript would have been lost on
> restart). This is often a full disk — free some space (or fix state.db
> permissions), then send your message again."

**That message names the wrong cause more often than the right one.** Observed
one occasion on host `the co-tenant host`: 40 GB free, inodes at 8%, permissions fine — the real
failure was b-tree corruption. Always run the disk check AND the log grep before
believing either:

```bash
df -h /; df -i /
grep -c "disk image is malformed" ~/.hermes/profiles/<p>/logs/gateway.log
```

Reporting "you're out of disk" off the error text alone, when `df` says
otherwise, is the failure mode this section exists to prevent.

## 1. Localize the damage before planning anything

Corruption is usually **per-table**, not whole-file. Count rows in every table
individually; the intact tables are what you will merge forward later.

```python
c = sqlite3.connect(path, timeout=30)
c.execute("PRAGMA query_only=ON")
for (t,) in c.execute("select name from sqlite_master where type='table'"):
    try:
        print("OK ", t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
    except Exception as e:
        print("ERR", t, e)
```

On the co-tenant host: `sessions` and `compression_locks` were destroyed; `messages` (448k
rows) and all FTS shadow tables were perfectly readable. That asymmetry is what
made merge-forward possible — check for it before assuming total loss.

Also check `dmesg` for real I/O errors. Their **absence** is meaningful: it says
software bug, not failing disk, which changes the remediation (upgrade SQLite vs
replace hardware).

## 1a. Suspect the SQLite WAL-reset bug first

The known software cause is the [WAL-reset corruption
bug](https://sqlite.org/wal.html#walresetbug). Vulnerable versions can corrupt
individual b-trees on a perfectly healthy disk under ordinary concurrent load.
Hermes already warns about it at **every gateway start**, once per process per
database:

> `WARNING hermes_state: state.db: linked SQLite 3.50.4 is vulnerable to the
WAL-reset corruption bug … Upgrade to SQLite 3.51.3+ (or backports 3.50.7 /
3.44.6)`

Grep the gateway log for `walresetbug` before theorizing, and read the linked
version from the **venv Python**, not the system `sqlite3` CLI — they routinely
differ and only the linked one matters:

```bash
~/.hermes/hermes-agent/venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Fixed at **3.51.3+**, or backports 3.50.7 / 3.44.6. Hermes-managed installs
repair the embedded runtime with `hermes update`.

**Repairing the database does not remove the cause.** After recovery, audit the
linked version on every host and report which remain exposed — otherwise the
same corruption returns on the same box. Calling a host "fixed" while it still
links a vulnerable SQLite is a half-truth; state both facts and let the owner
decide on the restart window.

## 2. Do not try to salvage a corrupt table row-by-row

Two dead ends, both worth knowing so you skip them:

- **`sqlite3.recover` is unavailable on stock Ubuntu builds.** It fails with
  `sql error: no such table: sqlite_dbpage (1)` because the distro CLI is built
  without the dbpage vtab. It exits non-zero having written a 0-byte output
  file, so check the output size, not just rc.
- **Index-driven salvage does not work on a damaged b-tree.** A surviving index
  may still return a handful of keys (675 of 13,742 real rows on the co-tenant host) and
  `max(rowid)` may return an absurd value (412,316,877,386) — that number _is_
  the corruption. Every `where rowid=?` fetch then fails. A partial index scan
  is not a partial recovery; it is noise.

Go to backup. That is the answer.

## 3. Restore ONE file from restic, verify before using it

```bash
eval "$(grep '^export AWS_' ~/.hermes/scripts/backup-to-s3.sh)"   # see pitfall
REPO="s3:s3.amazonaws.com/openclaw-fleet-backups/$(hostname -s | tr '[:upper:]' '[:lower:]')"
restic -r "$REPO" --insecure-no-password snapshots --latest 4
restic -r "$REPO" --insecure-no-password restore <snapid> \
  --target /path/to/scratch \
  --include /home/ubuntu/.hermes/profiles/<p>/state.db
```

`--include` takes the **absolute path as stored in the snapshot**; the file
lands under `<target>/<that absolute path>`. Restoring one 5.7 GB file took 20 s.

Then require `pragma quick_check` → `ok` on the restored copy **before** planning
the swap. A backup you have not verified is not a backup.

## 4. Merge forward — and DETACH before you write

This is the subtle part. The obvious approach (ATTACH the live db, `INSERT INTO
main.x SELECT * FROM live.x`) **fails catastrophically at commit**: any read
error from a corrupt live table poisons the open write transaction, so the good
work done earlier in the same transaction is lost too. On the co-tenant host the first attempt
merged 107 sessions and 8,111 messages successfully, then died with
`sqlite3.DatabaseError: database disk image is malformed` at `m.commit()` and
discarded all of it.

Correct sequence:

1. ATTACH live, **read every needed row into Python memory**, wrapping each
   table in its own try/except so an unreadable table is skipped, not fatal.
2. `DETACH live`.
3. Only now write into the clean base, committing after each logical group.

```python
m.execute("ATTACH ? AS live", (live_path,))
staged, aux =..., {}
for t in aux_tables:                      # per-table tolerance
    try:    aux[t] = m.execute(f"select * from live.{t}").fetchall()
    except Exception as e: print("SKIP", t, e)
m.execute("DETACH live")                  # <-- before any write
# ... inserts + commit per group ...
```

Rows whose parent record lived in the destroyed table can be **synthesized** from
the surviving child rows — on the co-tenant host, 107 missing `sessions` rows were rebuilt from
`min(timestamp)`, `max(timestamp)`, `count(*)` of their messages, with
`source='recovered'` and a `[recovered]` title marker so they are auditable
later. Only populate columns that actually exist in the target schema
(`pragma table_info`), since schemas drift across versions.

Finish with an FTS rebuild so search matches the merged corpus:

```python
m.execute("insert into messages_fts(messages_fts) values('rebuild')")
```

## 5. Swap with the standard stop → prove absent → mutate → start → verify

Preserve the corrupt original under a diagnostic name rather than deleting it —
it is the only forensic artifact you have. Remove stale `-wal`/`-shm` while
stopped, since they do not match the new main image.

Verification that actually proves the fix (all four, not just the first):

- `systemctl --user is-active <svc>` and the expected PID present
- **zero** new `malformed` lines timestamped after the restart — grep with a
  time window, because the historical count stays non-zero forever
- the previously-broken tables now return counts through a live connection
- row counts still **increasing** a minute later, proving writes land

Observed downtime for a 5.7 GB db: ~90 s. Total wall time ~35 min, dominated by
FTS rebuild and `quick_check`, both of which run in uninterruptible `D` state —
that is normal, not a hang.

## Time budget for a multi-GB database

| Step                    | 5.7 GB observed |
| ----------------------- | --------------- |
| restic restore (1 file) | 20 s            |
| `quick_check`           | 8-12 min        |
| base copy               | 45 s            |
| FTS rebuild (448k rows) | ~15 min         |
| gateway downtime        | ~90 s           |

Run the long steps in the background with completion notification and do other
work; do not sit in a poll loop.

## Pitfalls

- **Reading a credentials file redacts the secrets.** Reconstructing an
  `export AWS_...` line from what you read gives `Access Denied`. Source the
  values on-host instead: `eval "$(grep '^export AWS_' <script>)"`.
- **`timeout` does not exist on macOS**, so a fleet loop that wraps ssh in
  `timeout` fails on every Mac target with `command not found`. Use
  `ssh -o ConnectTimeout=N` instead.
- **A bash `for` loop consumes the stdin you were piping to `ssh`.** A loop of
  `cat script | ssh $h 'bash -s'` returns empty for every host after the first.
  Redirect per-iteration (`< /dev/null` on the loop body) or run hosts
  individually.
- **Do not conclude "recovered" from a successful `start`.** Exit status of the
  supervisor command says nothing about whether the database is writable.
