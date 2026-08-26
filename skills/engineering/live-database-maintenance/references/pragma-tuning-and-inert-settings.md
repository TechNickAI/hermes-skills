# SQLite pragma tuning and the "configured setting never applies" bug class

Companion to the maintenance procedure. Covers reading live pragmas, benchmarking
them honestly on network storage, and the recurring defect where an application
exposes a tunable that silently reverts.

Measured on a 334 MB SQLite DB behind a Node service on AWS gp3 EBS, 2026-08-03.

---

## Read the LIVE pragmas before proposing anything

Source defaults are not what the database is running. Read the real values:

```js
const D = require("better-sqlite3")(DBPATH, { readonly: true });
for (const p of [
  "cache_size",
  "mmap_size",
  "wal_autocheckpoint",
  "page_size",
  "synchronous",
  "journal_mode",
  "busy_timeout",
])
  console.log(p, JSON.stringify(D.pragma(p)[0]));
```

Found live: `cache_size=-16000` (16 MB) while the source default said `65536`
(64 MB), and `mmap_size=0` despite source intent of 256 MB. **Both numbers were
real** — they came from different code paths. That discrepancy IS the bug; do not
average it away or assume one source is authoritative.

## The bug class: a setting that exists, is editable, and never applies

Symptoms that look unrelated but are one defect:

- The dashboard shows one value; the running database holds another.
- A user changes the setting; it works until the next restart, then reverts.
- Source says X, live says Y, and nobody can explain who wrote Y.

**Root cause pattern** — startup reads the _compiled-in default_ instead of the
_persisted value_:

```js
// core.ts — runs on every boot
db.pragma(`cache_size = -${DEFAULT_DATABASE_SETTINGS.optimization.cacheSize}`);
```

...while the persisted value is only applied by a separate function that fires on
a settings **save** (`applyDatabaseOptimizationSettings()`), not on boot. Net
effect: configuring the setting works exactly once per save and is lost on every
restart.

**Second, compounding root cause** — a UI fallback literal that contradicts the
default:

```jsx
cacheSize: parseInt(e.target.value) || 16384; // default elsewhere is 65536
```

Clearing the field or typing a non-number yields `NaN`, so `|| 16384` silently
writes a quarter of the intended default. This is usually how the mystery stored
value got there: nobody chose it, a fallback fired.

### How to diagnose it in ~4 greps

```bash
grep -rn "<settingName>" --include=*.ts --include=*.tsx src/   # types, API, UI, applier
grep -rn "<pragma_name>" --include=*.ts src/                    # every place applied
```

Then answer three questions in order:

1. Where is the default defined?
2. What is actually persisted (read the store directly)?
3. Which code path applies it **at startup**, and does that path read the store?

If (3) reads the default rather than the store, you have found it.

### Verify the "unset" path empirically, not by reading merge code

Copy the DB, delete the key, and see what the app computes:

```bash
cp live.sqlite /tmp/test.sqlite
node -e "const D=require('better-sqlite3')('/tmp/test.sqlite');
  D.prepare(\"DELETE FROM key_value WHERE key='cacheSize'\").run();"
```

A merge layer that clones defaults and overlays stored keys will fall back
correctly — but confirm rather than assume, and say which behavior you proved.

## Benchmarking pragmas on network storage: medians or nothing

EBS jitter swamps single-run signal. Same config, five alternating runs:

```
12 indexes: 7.76 / 4.24 / 0.78 / 0.73 / 0.78  -> median 0.781 ms
 9 indexes: 0.44 / 0.43 / 0.48 / 2.39 / 0.46  -> median 0.455 ms
```

10x spread **within one config**. Single-run comparisons produced "37x" and
"268x" claims that were retracted; the real effect was ~1.7x. Rules:

- Medians over many trials, alternating between configs.
- One variable at a time.
- Report the spread, not just the middle.
- If two configs' ranges overlap, you have no result.

### What actually moved (and what didn't)

```
                          reads       writes
cache 16 MB,  mmap 0     23.41 ms     (all within noise)
cache 256 MB, mmap 0     15.62 ms  <- 33% faster, tight and repeatable
cache 256 MB, mmap 512MB 15.62 ms  <- mmap adds nothing on top
```

**Cache size is the read-side win; write-side pragma tuning was noise.** Size the
cache against the DB, not against RAM: 256 MB held 77% of a 334 MB database, and
going higher gains little. Leaving `mmap_size` at 0 is defensible — no measured
benefit, and mmap with concurrent writers adds crash-consistency risk.

`synchronous` is a genuine lever but a _source_ change, not a runtime toggle:

```
OFF     0.066 ms/insert
NORMAL  5.017 ms          <- typical upstream default
FULL   14.548 ms
```

With WAL, `OFF` still survives process crashes; only the last WAL writes are at
risk on hard power loss. Reasonable for pure telemetry, not a decision to make
unilaterally.

## Index changes may not survive a restart

If the app runs `db.exec(SCHEMA_SQL)` on **every boot**, any index defined there
is recreated regardless of what you dropped. Only migration-created indexes
persist. Check before proposing index changes as a config fix — and run
`EXPLAIN QUERY PLAN` before calling any index redundant (all 12 were in use in
the case that prompted this).

## Two claims to stop making without measuring

- **"Big tables cause GC pressure."** Measured false: a 245k-row read moved the
  heap 4.1 MB. SQLite counts rows in native C, outside the JS heap.
- **"Table size is why the dashboard is slow."** It was EBS throughput
  saturation causing synchronous-driver event-loop stalls. See
  `performance-bottleneck-attribution`.

## Changing a setting when the settings API is broken

Management APIs often need a **dashboard session cookie**, not a bearer/API key:

```bash
PW=$(grep -m1 '^INITIAL_PASSWORD=' .env | cut -d= -f2-)
curl -s -c /tmp/ck -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" -d "{\"password\":\"$PW\"}"
curl -s -b /tmp/ck -X PATCH $BASE/api/settings/database \
  -H "Content-Type: application/json" -d '{"optimization":{...}}'
```

Watch for `schema.partial()` applied only at the **top level** — a partial nested
object gets rejected with per-field "expected number, received undefined" errors.
GET the current block, change one field, send it back whole.

If GET itself 500s, the API is not an option: fall back to
`stop → edit the store → start` (see the parent skill's sequencing rules — the
same page-cache hazard applies, ~17s downtime in practice).

## Sampling the right process

When attributing disk I/O, the process matching your service's command line may
be a **supervisor** that writes nothing. Its child does the work.

```bash
# scan every pid's counters, not just the one you expect
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  awk '/^write_bytes/{print $2}' /proc/$p/io 2>/dev/null
done
# then confirm identity via open fds
ls -l /proc/<pid>/fd | grep -E 'sqlite|\.log'
```

Observed: the supervisor reported 0 MB/s while its child wrote 200+ MB/s and held
all four SQLite fds (`.sqlite`, `-wal`, `-shm`, plus the app log).

Also beware measuring file growth against a stale baseline — a "DB grew 278 MB in
20 s" reading was an artifact of comparing against a pre-VACUUM size. Re-measure
before believing sudden growth.
