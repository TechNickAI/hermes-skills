# Backing up SQLite when the app is on a full-rewrite driver (sql.js)

Worked case 2026-08-14, the router, before a v3.8.50 deploy. the operator asked
for "triple backups — I don't want to have to rebuild my configuration."
Two reasonable-looking backup methods produced **corrupt files** before the
third worked. Both failures looked like data corruption and were not.

## Symptom

`pragma quick_check` on the LIVE db returns `ok`, but the copy you just made
reads `database disk image is malformed` / `SQLITE_CORRUPT`. Separately, the
live file can be observed at **0 bytes** with `page_count 0`, seconds after
reading clean at 432 MB.

Neither is corruption. Both are artifacts of _how the app writes_.

## Root cause: the driver re-serializes the whole file

When Next's `serverExternalPackages` externals handling fails to preserve a
dynamic `require`, the app silently falls back to the **sql.js WASM driver**.
sql.js has no incremental persistence — every write debounces into
`db.export()` + `fs.writeFileSync` of the ENTIRE database.

Consequences for anything that reads the file:

- There is a window on every write where the file is truncated or partial. A
  reader landing in it sees `SQLITE_CORRUPT`, `SQLITE_ERROR`, a short file, or
  size 0. This is a **torn read**.
- `journal_mode` reads `delete`, not `wal`, and `-wal` stays 0 bytes. sql.js
  does not use WAL at all — so WAL-based reasoning about consistency does not
  apply here.

## Trap 1: the host python is a different SQLite than the writer

```
host python3 -c "import sqlite3; print(sqlite3.sqlite_version)"   -> 3.45.1
app better-sqlite3 "select sqlite_version()"                      -> 3.53.3
```

A backup taken with **python's** `sqlite3` `.backup()` API produced a file that
BOTH python and better-sqlite3 subsequently read as `SQLITE_CORRUPT`. The
source was fine the whole time.

**Rule: back up a database with the same engine that writes it.** On this host
that means the app's own `better-sqlite3`, run from inside the standalone
bundle so module resolution works:

```bash
cd ~/src/the router/current/.build/next/standalone && node backup.cjs
```

The same host's `sqlite3` CLI is also 3.45.1 and cannot read the DB at all —
it reports real tables as `no such table`.

## Trap 2: `VACUUM INTO` is not torn-read safe either

`VACUUM INTO` fails with `database disk image is malformed` when it lands in a
rewrite window, same as everything else. It is not a more robust alternative.

## The working pattern: retry until provably consistent

Use `.backup()` and **re-verify the copy**, retrying on failure. Do not accept
a copy because the call returned without throwing.

```js
const B = require("better-sqlite3");
const TABLES = ["combos", "provider_connections", "api_keys"]; // config tables

function inspect(p) {
  const d = new B(p, { readonly: true, fileMustExist: true });
  try {
    const qc = d.pragma("quick_check")[0].quick_check;
    const counts = {};
    for (const t of TABLES)
      counts[t] = d.prepare(`select count(*) c from ${t}`).get().c;
    return { qc, counts };
  } finally {
    d.close();
  }
}

async function retrySnapshot(live, dst, expect, tries = 40) {
  for (let i = 1; i <= tries; i++) {
    try {
      if (fs.existsSync(dst)) fs.unlinkSync(dst);
      const src = new B(live, { readonly: true, fileMustExist: true });
      try {
        await src.backup(dst);
      } finally {
        src.close();
      }
      const got = inspect(dst);
      if (
        got.qc === "ok" &&
        JSON.stringify(got.counts) === JSON.stringify(expect)
      )
        return true;
    } catch (e) {
      /* torn read — retry */
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}
```

Notes that made this correct:

- **Read the source truth with the same retry loop.** The first consistent read
  of the live DB is what you compare copies against.
- **Exclude high-churn tables from the equality gate.** `call_logs` changes
  every second; gating on it makes every backup "fail". Gate on the config
  tables the user actually cares about losing.
- Observed needing up to **3 attempts** per copy. Torn reads are common, not rare.
- Verify by _opening and counting rows_, never by file size or exit code.

## What "triple backups" should actually mean

Three copies on one filesystem is one failure domain. Spread them:

| copy | location                                     | survives                        |
| ---- | -------------------------------------------- | ------------------------------- |
| 1    | app's own backup dir on the host             | fast local restore              |
| 2    | a different dir/mount on the host            | one path being clobbered        |
| 3    | `/var/tmp`, outside the app tree             | a bad deploy wiping the app dir |
| 4    | **off-host** (scp to the operator's machine) | loss of the host                |

Back up the **config env file alongside it** — `.env` holds
`STORAGE_ENCRYPTION_KEY` and provider credentials. A restored DB without its
encryption key is unreadable, so the DB alone does not satisfy "I don't want to
rebuild my configuration."

Report a sha256 per copy. Copies taken seconds apart legitimately differ when a
churn table is live; say that out loud rather than presenting it as an
inconsistency the user has to interpret.

## Do not panic on a 0-byte live database

Mid-session the live file showed 0 bytes and `page_count 0` while the service
kept serving traffic normally. That was a write window. Before escalating a
suspected data-loss event on a full-rewrite driver:

1. Sample `stat -c %s` several times over ~10s — a live file oscillating in
   size is being rewritten, not destroyed.
2. Re-read with the app's engine, with retries.
3. Check the service is still answering requests.

## Verifying WHICH driver is actually live (two independent signals)

Do not infer the driver from log silence or from what is on disk. The package
and its compiled `.node` can be present and correctly requireable by hand while
the compiled code path can never reach them.

```bash
# 1. is the native module actually dlopen'd into the running process?
sudo grep -c 'better_sqlite3\.node' /proc/<pid>/maps      # 0 == NOT loaded
sudo grep -oE '/[^ ]*\.node' /proc/<pid>/maps | sort -u   # what IS loaded

# 2. behavioural: full-file rewrite rate
a=$(stat -c%Y $DB); n=0
for i in $(seq 1 10); do m=$(stat -c%Y $DB); [ "$m" != "$a" ] && { n=$((n+1)); a=$m; }; sleep 1; done
echo "full-file rewrites in 10s: $n"
```

Observed on the broken build: **0** matches for `better_sqlite3.node`, and
**5 rewrites per 10s** of a 432 MB file ≈ 216 MB/s sustained. Two signals
agreeing is what makes the diagnosis reportable.

Remember the process tree: systemd `MainPID` is often a wrapper
(`/usr/bin/node dev/run-standalone.mjs`). Inspect the **child** pid's maps.

## Ordering rule: never remove the workaround before the fix is proven live

The DB had been moved to a tmpfs RAM disk specifically because this write storm
was destroying EBS burst credits. The user's ask was "undo the temp FS hack
when we launch the new one."

The correct answer was **not yet** — because the fix was in the new code but the
_running_ build still had the bug, and the tmpfs was the only thing absorbing
216 MB/s. Undoing it first would have aimed the storm at a gp3 volume rated
500 MB/s.

Correct sequence for retiring any performance workaround:

1. Deploy the fix.
2. Prove the fix is live in the **new process** (here: `better_sqlite3.node`
   mapped in `/proc/<newpid>/maps`).
3. Prove the _behaviour_ changed (rewrite rate collapses).
4. Only then remove the workaround.

A workaround is load-bearing until measurement says otherwise. "The fix is
merged" is not measurement.

**Corollary: a watchdog can hide that the workaround is still load-bearing.** On
this host a self-heal watchdog was restarting the service roughly every 12h for
"memory crisis" (RSS 4.32 GB vs 1.46 GB baseline, external buffers 33x baseline,
four times in 72 hours). Same root cause — sql.js holds the whole DB in memory
and re-serializes it, so the write storm and the "leak" were one bug. Recurring
automated restarts are evidence the underlying condition is still live. Check
the restart history before declaring any mitigation unnecessary.
