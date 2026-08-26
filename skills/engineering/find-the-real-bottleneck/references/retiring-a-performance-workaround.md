# Retiring a performance workaround

**Load when** a hack was installed to survive a bug (RAM disk, cache layer,
raised capacity tier, rate limiter, aggressive retry) and the underlying bug has
since been fixed. The question "do we still need this?" is answerable by
measurement, not by argument.

Worked end-to-end on the One case: a tmpfs RAM disk had been
added to absorb ~216 MB/s of writes caused by a sql.js WASM fallback
re-serializing a 423 MB database on every write. Once the native `better-sqlite3`
driver was actually loading, the question was whether the RAM disk should stay.

## The trap: "is the workaround faster?" is the wrong question

The RAM disk **was** genuinely faster — measured, 3.9x. If that had been the
question, the answer would have been "keep it," and it would have been wrong.

The right question is **does the difference matter at the demand we actually
serve?** Those are different questions and they had opposite answers here.

```
tmpfs: 32,434 SQLite ops/sec
EBS: 8,382 SQLite ops/sec <- 3.9x slower, and completely irrelevant
demand: 0.83 writes/sec <- busiest minute in 24h
```

10,099x headroom on the _slow_ option. Report both numbers together or the
speed figure alone will drive the wrong decision.

## Step 1 — A/B the storage/resource layer in isolation, interleaved

Production comparison confounds the thing you are testing with traffic volume,
model mix, and time of day. Build a microbenchmark that varies **only** the
backend, and alternate the arms so load drift hits both equally.

```
for round in 1 2 3; do
  for tgt in /mnt/ramdisk /home/ubuntu/.appdata; do
    node bench_storage.cjs "$tgt" 3000
  done
done
```

Results were tight across rounds (29.4k / 35.5k / 32.4k vs 8.2k / 7.8k / 9.1k),
which is what earns the right to quote a ratio. If within-arm spread had rivaled
between-arm difference, the honest answer would be "no measurable effect" — see
the noise-floor protocol in the parent skill.

**Model the real access pattern, not `dd`.** The benchmark replicated what the
service actually does: row inserts with a ~1KB payload column, an upsert against
a small aggregate table, periodic reads, a WAL checkpoint every 400 writes, and a
final `wal_checkpoint(TRUNCATE)`. Use the app's own driver and the app's own
pragmas (`journal_mode`, `synchronous`) — a benchmark on different pragmas is
measuring a different system.

## Step 2 — Measure real demand from production data, including the peak

Typical load is not the number that decides it; the worst observed minute is.

```sql
-- typical, several windows
select count(*) from call_logs where timestamp >= <t-1h>;

-- the peak minute in 24h, which is what capacity must cover
select substr(timestamp,1,16) m, count(*) c
from call_logs where timestamp >= <t-24h>
group by m order by c desc limit 3;
```

Measured: 0.247 writes/sec typical, 0.83 writes/sec at the busiest minute.

## Step 3 — Convert the gap into user-visible cost

A ratio is not an impact. Divide the per-operation difference into the actual
request latency:

```
insert p95: tmpfs 0.024 ms vs EBS 0.057 ms -> +0.033 ms
as a share of a 5,643 ms p50 request -> 0.0005%
```

Also separate **in-request** cost from **background** cost. WAL checkpoints went
0.2 ms → 8.9 ms, a 44x regression that is genuinely invisible because checkpoints
are not in the request path. Say which is which; a large-looking regression in a
background path is not a reason to keep a hack.

## Step 4 — Price what the workaround costs to keep

The hack is never free. Enumerate:

- **198 GB/day** of pure duplicate writes (a 423 MB DB synced to disk every 180s)
- a 1.5 GB tmpfs ceiling against a 423 MB DB that grows
- total data loss on reboot if the sync ever failed silently
- 714 orphaned `.tmp.<pid>` files leaked by the sync script
- a `RequiresMountsFor=` dependency plus ExecStartPre/ExecStopPost hooks that
  every future operator has to understand

## Step 5 — Migrate with verified equivalence, not a copy

Row counts **and** `quick_check` before and after, compared as strings:

```
before: {"combos":10,"provider_connections":16,"api_keys":12,"quick_check":"ok"}
after: {"combos":10,"provider_connections":16,"api_keys":12,"quick_check":"ok"}
```

Abort the migration if they differ. Specific traps:

- **Remove symlinks before copying.** If `~/.appdata/db.sqlite` is a symlink into
  the ramdisk, `cp ramdisk/db.sqlite ~/.appdata/db.sqlite` follows the link and
  copies the file onto itself. `rm -f` the three symlinks (db, `-wal`, `-shm`)
  first, then copy real files into place.
- **Stop the periodic sync timer before touching anything**, or it writes
  underneath the migration.
- **Assert the unit is clean afterward**: `grep -qE "ramdb" "$UNIT"` must fail.
  Rewriting a systemd unit with a regex and not re-reading it is how a stale
  `RequiresMountsFor` survives and blocks the next boot.
- **Leave the old backing store mounted but unused.** Rollback then costs
  seconds instead of a re-provision, and it is free to keep for a few days.

## Step 6 — Prove the new path is actually in use

Health 200 does not prove which file the process opened. Read the file
descriptors:

```
sudo ls -l /proc/<child-pid>/fd | grep sqlite
  22 -> /home/ubuntu/.the router/storage.sqlite
  23 -> /home/ubuntu/.the router/storage.sqlite-wal
  24 -> /home/ubuntu/.the router/storage.sqlite-shm
```

Corroborate with mtimes: the old location must go **stale** while the new one
advances. Note the fd lives on the _child_ process if the entrypoint is a
wrapper — checking the parent PID reports nothing and reads as failure.

## Step 7 — Same-method before/after under real traffic

Re-run the identical probes used for the baseline. Not similar ones — identical.

| metric             | with workaround     | after removal |
| ------------------ | ------------------- | ------------- |
| disk writes / 60s  | 447 MB              | 20 MB         |
| process write rate | ~216 MB/s (pre-fix) | 103 KB/s      |
| disk `%util`       | 11.6%               | 0.10%         |
| RSS                | 2.75 GB             | 1.50 GB       |
| request p50        | 6,068 ms            | 5,643 ms      |

**Do not claim the latency win.** p50 improved 425 ms, and the honest reading is
traffic mix, not storage — the storage delta was measured at 0.033 ms. Saying
"removing the RAM disk made requests faster" would be a fabricated arrow. State
it plainly: "latency improved slightly; that's traffic mix, not storage."

## Step 8 — Re-derive the capacity decision

Removing a workaround usually invalidates provisioning that was sized for it.
Here the 231 MB/s sync bursts were the only justification for 500 MiB/s of
provisioned EBS throughput; sustained writes afterward were ~0.3 MB/s, making the
premium pure waste. Check the cooldown before stepping (EBS modifications are
locked for 6 hours), so you size once rather than twice.

## Reporting shape

Lead with the verdict and the number that decided it, then show that you tested
the opposite case honestly:

> The tmpfs is gone. It **was** 3.9x faster — and that mattered 0.0005% per
> request, against 10,099x headroom on the slower option. It was compensating
> for the driver bug, not for slow disk.

Admitting the workaround won the raw benchmark is what makes the recommendation
credible.
