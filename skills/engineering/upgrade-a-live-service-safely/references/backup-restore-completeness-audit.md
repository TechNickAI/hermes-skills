# Backup restore-completeness audit

A backup job that exits 0 every night proves it ran. It does not prove that
restoring from it produces a **working service**. Those are different claims,
and the gap between them is only visible if you deliberately go looking.

Worked case, one occasion, the router production router. The restic→S3 job had been
green for months. Its backup root was `~/.the router`, which contained the SQLite
database holding all routing configuration — combos, provider connections, API
keys. Looked complete. It was not.

## The question to ask

Not _"is the backup running?"_ but:

> **If this host burned down, what exactly would I be unable to reconstruct
> from the backup alone?**

Answer it by enumerating the application's real inputs and checking each one
against the backup root set — not by reading the job's exit status.

## Failure 1 — application state outside the backup root

```bash
# what the job actually backs up
grep -nE '^TARGET=|backup |--exclude' ~/scripts/backup-to-s3.sh

# what the snapshot actually CONTAINS (authoritative — the script can lie)
restic -r "$REPO" snapshots --latest 1
restic -r "$REPO" ls <snapshot-id> | grep -E '^/path/[^/]*$'
```

The backup root was `/home/ubuntu/.the router`. The config file lived at
`/home/ubuntu/src/the router/.env` — **outside it.** Nothing errored, because a
backup root is a positive assertion; it cannot warn about what you did not name.

This is a recurring structural class, not a one-off. The same shape destroyed
a trading agent's trading state: nightly restic covering only `$HOME/.hermes` while live
state sat in `/home/ubuntu/a trading agent/shared/`, green job throughout.

**Audit the backup ROOT SET per host. Never infer coverage from a green job.**

## Failure 2 — encrypted-at-rest data whose key is not in the backup

This is the sharpest version of the above, because the backup _appears_ to
contain everything important.

```
provider_connections.access_token  prefix="enc:v1:7c90a"  len=3721
provider_connections.access_token  prefix="enc:v1:c8a8c"  len=289
```

`enc:v1:` — ciphertext. The decryption key (`STORAGE_ENCRYPTION_KEY`) lived only
in the un-backed-up `.env`. So a restore would have produced a database with 16
provider connections that **could not be decrypted**: every OAuth provider
re-authenticated by hand, which for subscription-backed providers is not a
five-minute job.

Cheap detection — dump a token prefix and classify it:

```js
const t = db
  .prepare(
    "select access_token from provider_connections " +
      "where length(coalesce(access_token,''))>0 limit 1",
  )
  .get().access_token;
const plaintext = /^(sk-|gho_|ya29|eyJ)/.test(t); // known credential prefixes
console.log(
  plaintext ? "PLAINTEXT" : "ENCRYPTED — key must be in the backup set",
);
```

**Rule: whenever a datastore holds encrypted-at-rest secrets, the key material
is part of the backup set by definition.** Backing up ciphertext alone is
backing up nothing.

## Failure 3 — a silent stale lock skipping retention forever

The nightly job printed `snapshot saved` and exited 0, but the _next_ stage
failed:

```
repo already locked, waiting up to 0s for the lock
unable to create lock in backend: repository is already locked by PID 614122
lock was created at one occasion 19:28:48 (20m56s ago)
```

`forget --prune` had been silently skipped — visible only as snapshot count
drifting above the retention policy (12 present under a 7-daily/4-weekly policy).
The backup step succeeding masked the retention step failing.

```bash
ps -p <PID> >/dev/null 2>&1 || restic -r "$REPO" unlock   # confirm dead FIRST
```

**Check the lock holder is actually gone before unlocking.** Blindly unlocking a
live repo corrupts a concurrent run. And note the general shape: a multi-stage
job whose exit code reflects only the first stage will hide every later failure.

## Verify by RESTORING, not by reading the manifest

A file listed in `restic ls` is evidence it was captured, not that it comes back
intact. Do the round trip and compare hashes:

```bash
restic -r "$REPO" restore <snap> --target /tmp/restore-test --include /path/to/.env
diff <(sha256sum < /path/to/.env) <(sha256sum < /tmp/restore-test/path/to/.env) \
  && echo "MATCH — byte-identical"
grep -c '^STORAGE_ENCRYPTION_KEY=' /tmp/restore-test/path/to/.env   # key survived
rm -rf /tmp/restore-test
```

Then assert the _semantic_ property, not just the bytes: the restored config
contains the key that decrypts the restored database. That is the actual
recovery requirement.

## Checkpoint the WAL before snapshotting

Once a database is on real disk (not tmpfs), it carries a live `-wal`. A
snapshot of the main file without a matching WAL can miss recent commits.
Fold committed pages in first — best-effort, never fatal, and `PASSIVE` does
not block writers:

```bash
(cd "$BUNDLE" && node -e '
  const B = require("better-sqlite3");
  const d = new B(process.env.DBPATH, { fileMustExist: true });
  d.pragma("wal_checkpoint(PASSIVE)");
  d.close();
') >/dev/null 2>&1 || echo "WAL checkpoint skipped (non-fatal)"
```

⚠️ Exclude patterns are literal. `--exclude '*.db-wal'` does **not** match
`storage.sqlite-wal` — no `.db` in the name. Verify what an exclude actually
excludes by listing the snapshot, not by reading the glob and assuming.

## Also worth cleaning while you are there

A removed workaround leaves debris inside the backup root that inflates every
future snapshot: 714 orphaned `storage.sqlite.persist.tmp.*` files from a
retired ramdisk sync, plus the now-dead `.persist` copy itself. Retire the
artifacts with the mechanism.

## Checklist

1. Enumerate the app's real inputs: data dir, config/env files, credentials,
   TLS material, anything the service reads at boot.
2. Diff that list against the backup root set — and against an actual
   `restic ls`, since the script and the snapshot can disagree.
3. Classify stored secrets: is anything ciphertext? Where is its key?
4. Restore into a throwaway target and compare hashes.
5. Confirm every stage of the job succeeded, not just the first.
6. State the exposure plainly: what would have been unrecoverable, and for
   how long that was true.
