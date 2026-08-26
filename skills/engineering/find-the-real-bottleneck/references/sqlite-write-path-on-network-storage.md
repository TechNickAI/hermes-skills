# SQLite write-path performance on network-attached storage

Context: a Node service (better-sqlite3, synchronous API) fronting heavy traffic,
DB on EBS gp3. Symptom: dashboard pages and even 404s took 4–30s while the
service was otherwise healthy. Everything below is measured, not inferred.

## The decisive numbers

**Raw fsync latency, EBS vs RAM:**

```
EBS (/tmp)     p50= 76.9ms  p90=130.5ms   (earlier sample: p50=32ms, max=126ms)
tmpfs (/dev/shm) p50= 0.000ms  p90= 0.000ms
```

EBS is network-attached. Local NVMe is ~0.1ms. This is a 100–700x gap and it is
the single largest term in the write path.

**`synchronous` pragma, same schema, same rows:**

```
synchronous=OFF     0.066 ms/insert
synchronous=NORMAL  5.017 ms/insert    <- the app's setting
synchronous=FULL   14.548 ms/insert
```

76x between OFF and NORMAL. The cost is the durability barrier, not CPU.

**Native lib does NOT touch the JS heap** (kills any "big table → GC" theory):

```
heapUsed  before=3.6MB  after settings query=4.1MB
          after 20x COUNT on a 245k-row table=4.1MB
external  1.5MB -> 1.5MB     arrayBuffers 0.1MB -> 0.1MB
```

## Why this stalls the whole service

`better-sqlite3` is **synchronous**. Every query blocks Node's single event loop
until it returns — there is no async escape hatch. So one contended write parks
_all_ request handling, which is why an unrelated 404 took 5.58s.

The library's own source comments the tradeoff:

> "better-sqlite3 is synchronous, so a contended write parks the Node event loop
> for up to busy_timeout ms (a 0-CPU freeze that stacks under load → /health
> stops responding)."

**"0-CPU freeze" is the key phrase.** CPU-vs-wall accounting confirmed it:
wall 5,583ms vs CPU 2,360ms — only 42% burning, the rest waiting. Adding vCPUs
cannot fix a thread that is idle-blocked on disk.

## EBS volume saturation — check CloudWatch before recommending IOPS

### ⚠️ Unit trap: EBS Ops/Bytes metrics are SUMS over the period, not rates

This burned a full analysis cycle and produced a **wrong recommendation** that
was caught only on re-check. `VolumeWriteOps` and `VolumeWriteBytes` are counters
**summed over the `--period` window**. Querying them with
`--statistics Average Maximum` returns the average/max _per datapoint within the
bucket_, which is a meaningless number that looks like a plausible rate.

```
WRONG (--statistics Average, period=300, read as a rate):
  Write IOPS  avg 22,000–28,000  max 31,839   -> "7–10x over the 3,000 cap!"
  Write bytes avg 5.5 GB/s       max 7.9 GB/s -> "44–63x over the 125 MB/s cap!"

RIGHT (--statistics Sum, then divide by period seconds):
  Write IOPS       ~365–470 peak      of 3,000 provisioned =  14%   NOT saturated
  Write throughput ~110–120 MB/s      of  125 provisioned  =  94%   SATURATED
```

**Always use `--statistics Sum` and divide by the period.** The corrected picture
inverted the recommendation: IOPS was nearly idle, _throughput_ was the wall.
Provisioning IOPS would have cost money and changed nothing.

### Derive which dimension you need

```
avg write size = throughput ÷ IOPS = 110 MB/s ÷ 430 IOPS ≈ 256 KB per op
```

Large sequential writes saturate **bandwidth**; many tiny random writes saturate
**op count**. Compute this before choosing what to provision.

### Two corroborating signals

**`VolumeQueueLength` sustained > 1** means the volume is the bottleneck:

```
avg_queue 1.55–2.01 typical, spiking to 4.59 (max 8.93)
```

Treat queue as corroboration, not a standalone verdict. Compare all three
ceilings separately:

1. Volume-provisioned IOPS and throughput (`describe-volumes`).
2. Instance-type EBS baseline/max (`describe-instance-types` →
   `EbsOptimizedInfo`). The instance channel can bind before the volume.
3. Observed one-minute `Sum / 60` rates, plus sustained queue depth and
   `EBSIOBalance%` / `EBSByteBalance%` where available.

A multi-GB WAL can coexist with substantial unused EBS capacity. If observed
IOPS/throughput remain below both ceilings and balance metrics stay near 100%,
classify disk as a latency/recovery amplifier, not the cause of SQLite
`database is locked`. SQLite lock errors are logical writer/transaction
contention; prove hardware saturation separately before buying capacity.

Also verify the device class from both sides: `lsblk` may call an EBS device
`nvme0n1`, which does **not** make it local instance-store NVMe. Correlate its
serial/model with the EC2 block-device mapping. Confirm enhanced monitoring
live before enabling it; do not mutate AWS configuration when it is already on.

**A `dd` benchmark that underperforms the provisioned cap is itself the tell.**
`dd` measured only 57.6 MB/s on a volume provisioned for 125 MB/s — because the
application was already consuming ~110 MB/s of it. Contention for a saturated
cap, demonstrated directly rather than inferred.

### Measurements go stale — re-baseline before acting

fsync p50 measured **77ms** early in the session and **1.03ms** after a DB
cleanup (520→331 MB) plus a service restart. Same host, same volume, same day.
Any remediation argued from the stale number would have been aimed at the wrong
target. Re-run the baseline immediately before proposing a change.

**Commands to reproduce (requires aws cli on the host):**

```bash
VOL=$(aws ec2 describe-volumes --filters \
  Name=attachment.instance-id,Values=$(curl -s -H "X-aws-ec2-metadata-token: \
  $(curl -s -X PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60") \
  http://169.254.169.254/latest/meta-data/instance-id) \
  --query 'Volumes[0].[VolumeId,VolumeType,Size,Iops,Throughput]' \
  --output text --region ca-central-1)

# NOTE: dimension syntax is Name=VolumeId,Value=<id>  (Value, singular —
# "Values" is valid for ec2 filters but INVALID for cloudwatch dimensions
# and fails with a ParamValidation error).

# IOPS: Sum / period_seconds
aws cloudwatch get-metric-statistics --namespace AWS/EBS \
  --metric-name VolumeWriteOps --dimensions "Name=VolumeId,Value=$VOL" \
  --start-time $(date -u -d "6 hours ago" +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 --statistics Sum --region ca-central-1 --output text \
  | grep DATAPOINTS | sort -k3 \
  | awk '{printf "  %s  %7.1f IOPS\n", $3, $2/300}'

# Throughput: Sum / period_seconds / 1MiB, shown as % of provisioned
aws cloudwatch get-metric-statistics --namespace AWS/EBS \
  --metric-name VolumeWriteBytes --dimensions "Name=VolumeId,Value=$VOL" \
  --start-time $(date -u -d "6 hours ago" +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 --statistics Sum --region ca-central-1 --output text \
  | grep DATAPOINTS | sort -k3 \
  | awk '{mb=$2/300/1048576; printf "  %s  %6.1f MB/s  %5.1f%%\n", $3, mb, mb/125*100}'

# Queue depth: sustained >1 means the volume gates the workload
aws cloudwatch get-metric-statistics --namespace AWS/EBS \
  --metric-name VolumeQueueLength --dimensions "Name=VolumeId,Value=$VOL" \
  --start-time $(date -u -d "3 hours ago" +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 --statistics Average Maximum --region ca-central-1 --output text
```

**gp3 caps and pricing (verify current rates before quoting):**

```
                 baseline (free)   max        price above baseline
IOPS             3,000             16,000     ~$0.005/IOPS-month
Throughput       125 MB/s          1,000 MB/s ~$0.040/MB-s-month
```

Worked example: 125 → 1,000 MB/s = +875 MB/s ≈ **+$35/month**, IOPS untouched.
Provision only the dimension you proved is saturated. If the workload genuinely
exceeds gp3 caps, options are **io2 Block Express** or instance-store NVMe.

## VALIDATED: raising gp3 throughput (before/after from an identical harness)

The saturation analysis above was acted on and re-measured with the same script.
Changed **exactly one variable** — `aws ec2 modify-volume --throughput 125 → 250`
(live, no downtime, no restart, applies while state shows `optimizing`):

```
                        BASELINE      AFTER-250     change
dd sequential write      57.6 MB/s     162 MB/s     2.8x
SQLITE_INSERT_MEDIAN      1.402 ms     0.475 ms     2.9x
HTTP_MEDIAN               1.908 s      0.734 s      2.6x
HTTP_P90                  2.352 s      1.320 s      1.8x
HTTP_MAX                  3.541 s      1.526 s      2.3x
```

The `dd` figure is the cleanest evidence the cap was the constraint: same
command, same disk, 57.6 → 162 MB/s purely from raising the limit. Cost: +$5/mo
(125 extra MB/s × $0.040). **Prefer a modest bump you can validate over jumping
to the cap** — 250 MB/s bought 2.6x for $5; the 1,000 MB/s option was $35.

**But note the bottleneck moved rather than vanished:**

```
DISK_WRITE_MBPS=217   of 250 provisioned = 87%   (immediately re-saturated)
FSYNC_P50   1.034 → 1.959 ms
FSYNC_P90   1.385 → 52.970 ms      <- tail got WORSE
```

The service simply wrote faster into the new headroom. When a paid capacity bump
is instantly re-consumed, that is Phase 2d evidence of an underlying
amplification bug — say so rather than proposing the next tier.

### Diminishing returns confirmed at the next tier (250 → 500 MB/s)

Bumped again to 500 MB/s (+$15/mo over the original 125). Same `dd` probe:

```
125 MB/s cap:   57.6 MB/s
250 MB/s cap:  162   MB/s     <- 2.8x, dashboard median 1.908s -> 0.734s
500 MB/s cap:  322   MB/s     <- 2.0x more, dashboard median ~0.26s
```

The step from 125→250 bought a larger _user-visible_ improvement than 250→500
did, which is the signal that the volume is ceasing to be the binding
constraint. `dd` reaching only 322 of 500 MB/s is expected and healthy here —
the application holds the rest of the pipe, and the point is having headroom
rather than hitting the number.

**Recommend letting a tier settle under real load before buying the next one.**
Each doubling is cheap in isolation and easy to keep climbing reflexively; the
honest framing is that throughput bumps stopped being the lever once the
diminishing-returns knee appeared, and the unexplained write amplification is
the remaining term.

## Pragma tuning: cache_size / mmap_size / wal_autocheckpoint

Measured on a 334 MB DB, 16 MB cache (holds ~5% of the file). Question was
whether a bigger cache helps, given the host had plenty of free RAM.

**Writes — no usable effect** (3 trials, median, 150 inserts each):

```
CURRENT cache16M mmap0    ckpt1000    0.523 ms
cache256M        mmap0    ckpt1000    2.031 ms
cache256M        mmap512M ckpt1000    1.478 ms
cache256M        mmap512M ckpt4000    0.652 ms
```

All inside the EBS noise floor; the ordering is not real. Do not tune write path
with cache size.

**Reads — real and repeatable** (3 trials, dashboard-style aggregates):

```
cache16M   mmap0      23.41 ms   (22.9, 23.4, 24.1)
cache256M  mmap0      15.62 ms   (15.4, 15.6, 16.4)
cache256M  mmap512M   15.62 ms   (14.4, 15.6, 16.2)
```

**~33% faster reads from cache alone; `mmap_size` adds nothing on top.** Tight
spread, so this one survives the noise-floor test unlike the write numbers.

Guidance:

- Size `cache_size` to hold most of the DB when RAM allows (`-262144` = 256 MB
  for a 334 MB file ≈ 77% resident). Going beyond DB size buys nothing.
- Leave `mmap_size` at 0 unless measured otherwise — no gain here, and mmap on a
  DB with concurrent writers adds crash-consistency risk for free.
- Leave `wal_autocheckpoint` alone absent evidence of checkpoint thrash. Verify
  thrash by watching the `-wal` file: if it stays at 0 bytes while the process
  writes hundreds of MB/s, checkpoint thrash is **not** the mechanism.

**Check live pragmas against source — they diverge.** Source declared
`cacheSize: 65536` (`src/types/databaseSettings.ts:132`, applied at
`core.ts:1186`) but the live DB reported `cache_size = -16000`. Sign convention
matters: **negative = KiB, positive = pages**. Read the live value with
`PRAGMA cache_size` before reasoning about it; something in the runtime path may
override the declared default.

## `synchronous` explained (for recommending a change)

| Value        | fsync behavior (WAL mode)           | Survives process crash           | Survives power loss / kernel panic |
| ------------ | ----------------------------------- | -------------------------------- | ---------------------------------- |
| `FULL` (2)   | every transaction + checkpoint      | yes                              | yes                                |
| `NORMAL` (1) | checkpoints only                    | **yes**                          | no — may lose last few txns        |
| `OFF` (0)    | never; kernel flushes when it likes | **yes** (OS owns the page cache) | no                                 |

In WAL mode, `NORMAL` is already not per-transaction-durable. Moving to `OFF`
gives up protection only against **power loss / kernel panic**, not against the
app crashing, OOM, or `systemctl restart`.

Judgment: for **telemetry** tables (usage/call logs the app itself calls
"best-effort"), losing the last ~2s on a hard power cut is acceptable. For
billing/auth state it is not. Decide per-DB, and say which class the data is in.

Note: `synchronous` is set in the app's source (`core.ts:1185`), not in `.env`
or a config file — changing it requires a source edit and build, not just a
config toggle. Same applies to index drops: `SCHEMA_SQL` runs on every boot
with `CREATE INDEX IF NOT EXISTS`, so dropped indexes self-heal.

## Index cost — measure, don't assume

`EXPLAIN QUERY PLAN` showed the planner using **all 12** indexes on the hot table
for distinct query shapes, so none was trivially dead. Three were left-prefixes
of composites (`timestamp`, `provider`, `model` vs `idx_uh_provider_model_timestamp`
and a timestamp-leading composite) — droppable in principle, and dropping them
showed **no read regression** (9.78ms vs 9.81ms on a dashboard-style aggregate).

Write benefit was real but modest and _very_ noisy: median 0.781ms (12 idx) vs
0.455ms (9 idx) across 5 alternating runs, with 10x within-arm spread. Report the
median and the spread; do not sell this as a large win.

## Retention pruning — what it actually does

Pruning 342k stale rows (520MB → 331MB, 12 tables) halved median endpoint
latency (2.2s → ~1.2s) but did not eliminate the problem — fsync freezes still
dominate. Pruning requires stopping the live process first (see case-study
reference for the page-cache overwrite mechanism). The app's own cleanup
scheduler (`startCleanupScheduler`) is written correctly but lives in a module
nothing imports — see `references/case-study-router-pinning-and-dead-code.md`.

## Remediation menu, ordered by measured leverage

1. **`synchronous=OFF`** for telemetry DBs — 76x on the dominant term. Config in
   principle, but if set in source (`core.ts`), needs a build.
2. **Move DB to tmpfs** with periodic snapshot to durable storage — removes fsync
   entirely (0.000ms). Costs: RAM, and a startup/restore + snapshot mechanism.
3. **Batch hot-path writes** — buffer rows, flush every 1–2s in one transaction.
   One fsync instead of hundreds. Correct fix; needs code.
4. **Prune retention** — helped (~2x on median endpoint latency), but the app's
   own cleanup scheduler may be dead code; see the "fix that can't survive"
   phase in SKILL.md.
5. **Drop prefix-covered indexes** — modest, noisy, and reverts on boot if the
   index lives in the startup `SCHEMA_SQL`.
6. **Provisioned IOPS (gp3)** — caps at 16k IOPS, maybe 5x on fsync. Costs money.
   Check CloudWatch first to confirm you're hitting the cap.
7. **Instance with local NVMe** — real fix for fsync, but check the family
   actually offers instance store; many general-purpose types (e.g. m8g) do not,
   and the `nvmeXn1` device in `lsblk` is usually just the EBS volume.

**Do NOT recommend more vCPU or more RAM for this failure mode.** The freeze is
0-CPU and the memory is unmanaged buffers.
