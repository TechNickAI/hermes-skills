# Retiring a performance workaround

A workaround installed during an incident outlives the incident. Once the root
cause is actually fixed, the hack is no longer neutral — it costs money, adds
failure modes, and (worst) its assumptions get baked into monitors that then
misreport reality.

This is the method for deciding whether a hack is still needed, proven end to
end on one occasion removing a tmpfs/ramdisk SQLite hack from the
production router.

## The trap: "it's faster, so keep it"

The ramdisk _was_ genuinely faster. Measured, not assumed:

```
tmpfs: 32,434 SQLite ops/sec
EBS: 8,382 SQLite ops/sec -> tmpfs is 3.9x faster
```

If you stop there you keep the hack forever. **Raw capability is the wrong
question. The question is capability against measured demand.**

```
production demand: 0.247 writes/sec typical
                    0.83  writes/sec  (busiest MINUTE in 24h)
EBS headroom: 10,099x the worst minute ever recorded
per-insert cost: +0.033 ms at p95
as a share of a 5,643 ms p50 request: 0.0005%
```

A 3.9x speed advantage that buys 0.0005% of a user-visible request is not a
reason to keep infrastructure. Meanwhile the hack was writing **198 GB/day** of
pure duplication and carried a hard 1.5 G ceiling against a 423 MB database that
grows.

## Step 1 — measure DEMAND from production data, not intuition

Get the real arrival rate out of the app's own tables, and get the _peak_, not
just the average. An average hides the minute that actually hurts.

```sql
-- typical
select count(*)/900.0  from call_logs where timestamp >= <15 min ago>;
-- peak minute in 24h  (the number the capacity decision hangs on)
select substr(timestamp,1,16) m, count(*) c
from call_logs where timestamp >= <24h ago>
group by m order by c desc limit 3;
```

## Step 2 — A/B the storage layer, interleaved

Production comparison alone confounds storage with traffic volume, model mix,
and time of day. Isolate the variable: identical workload, identical driver,
alternating targets, several rounds so load drift cancels out.

```bash
for round in 1 2 3; do
  for tgt in /mnt/ramdisk /home/user/.appdata; do
    node bench_storage.cjs "$tgt" 3000
  done
done
```

Model the REAL access pattern — the dominant insert, an upsert, periodic reads,
and WAL checkpoints — not a synthetic `dd`. Match production pragmas exactly
(`journal_mode`, `synchronous`); a benchmark at different durability settings is
measuring a different system. Report percentiles per operation class, not just
a total.

Interleaving matters: three consecutive tmpfs runs followed by three EBS runs
would attribute any load drift to the storage backend.

## Step 3 — separate request-path cost from background cost

Not all latency reaches the user.

```
insert p95: tmpfs 0.024 ms vs EBS 0.057 ms -> +0.033 ms, in the request path
WAL checkpoint: tmpfs 0.20 ms vs EBS 8.90 ms -> +8.7 ms, BACKGROUND
```

The checkpoint delta is 260x worse and irrelevant, because checkpoints are
periodic and off the request path. Classify each cost before weighing it.

## Step 4 — before/after with IDENTICAL methods

Capture the baseline immediately before the change, using the exact command you
will re-run after. Different methods produce uncomparable numbers.

```bash
# same 60 s sampler, before and after
A=$(awk '/nvme0n1 /{print $10}' /proc/diskstats); sleep 60
B=$(awk '/nvme0n1 /{print $10}' /proc/diskstats)
echo "sectors/60s: $((B-A))  = $(( (B-A)/2/1024 )) MB"
```

Result on the real migration:

| metric             | with hack           | without  | change  |
| ------------------ | ------------------- | -------- | ------- |
| EBS writes / 60 s  | 447 MB              | 20 MB    | −22x    |
| process write rate | ~216 MB/s (pre-fix) | 103 KB/s | −2,000x |
| disk `%util`       | 11.6%               | 0.10%    | —       |
| RSS                | 2.75 GB             | 1.50 GB  | −45%    |

**Report honestly which deltas the change caused.** Request p50 improved
6,068 → 5,643 ms across the same window, but that is traffic mix, not storage —
say so rather than claiming credit. Overclaiming here is how a false causal
story enters the record and misleads the next capacity decision.

## Step 5 — migrate reversibly, verify at each step

Structure the migration script so every stage proves itself:

1. **Row-count + `quick_check` the source** before touching anything; abort if
   the live DB does not pass.
2. Stop the service (drains + checkpoints), and **stop any sync timer** so
   nothing writes underneath the copy.
3. **Remove symlinks before copying** — a `cp` onto a symlink follows it and
   writes back into the thing you are migrating away from.
4. **Re-verify row counts and `quick_check` on the destination and compare to
   the pre-flight values.** Equal, or abort.
5. Rewrite the unit to drop the dependency, then `grep` the unit to prove no
   reference survives before `daemon-reload`.
6. Start, then confirm health, native driver, and a REAL request.
7. **Leave the old infrastructure mounted but unused** so rollback is fast, and
   ship an explicit `--rollback` path in the same script.

Downtime for the real migration: **12 seconds.**

## Step 6 — prove the new path is actually in use

Health-200 does not prove _which_ storage the process opened. Check the open
file descriptors of the CHILD process (the entrypoint is often a wrapper):

```bash
sudo ls -l /proc/$(pgrep -P $MAINPID | head -1)/fd | grep sqlite
# must point at the NEW path; the old file's mtime should go static
```

A frozen mtime on the old file plus live fds on the new one is the proof.

## 🔴 Step 7 — the hack's assumptions are encoded in your monitors

**This is the step that gets skipped, and it is the dangerous one.**

Monitors written during the incident describe the workaround as if it were
permanent truth. Remove the workaround and those rules become actively harmful:

- A charter said _"the DB is on tmpfs and gets fully rewritten, so NEVER trust
  `quick_check` on the live file."_ True while the hack was in place. After
  migration it means **a real corruption signal gets dismissed as normal.**
- A rule said _"never alarm on `external`/`arrayBuffers`."_ That rule existed
  only to suppress noise from the bug now fixed. Those numbers are meaningful
  again.
- Threshold checks referenced the removed mount (`ramdisk % full`,
  `on_ramdisk`), which now silently measure nothing.

**Whenever you remove infrastructure, grep every monitor, charter, and runbook
for its name and fix them in the same change.** A suppression rule written to
silence a specific bug must be retired with that bug, or it becomes a permanent
blind spot pointed at exactly the failure you most need to see.

## Also: helper scripts inside a release directory do not survive a cutover

Backup/diagnostic scripts dropped into `releases/<old>/...` vanish the moment
the `current` symlink moves. Keep operational tooling in a stable location
(`$HOME/`), or expect `MODULE_NOT_FOUND` at the worst moment. Related: a
`node -e` needing local modules must run with the bundle as CWD.
