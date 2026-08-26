# After the cutover: proving the fallback is gone, and not reverting too early

Companion to `webpack-externals-stub-and-driver-fallback.md` (diagnoses the
bundling defect and its four downstream symptoms) and
`verification-that-discriminates.md` (the verification traps). This file is the
POST-DEPLOY half: what to measure once the fix is live, what NOT to undo yet, and
what the fix will not improve.

Worked case: the router v3.8.50 cutover, one occasion.

## The before/after table is the deliverable

A cutover report should show the SAME metrics on the old and new process, so
"the fix works" is a measurement rather than a claim:

| metric                  | WASM fallback        |                       native driver |
| ----------------------- | -------------------- | ----------------------------------: |
| `arrayBuffers`          | 1,326 MB             |                     17 MB (**76x**) |
| `external`              | 1,410 MB             |                                8 MB |
| RSS                     | 2.9–4.3 GB, climbing |                       1.25 GB, flat |
| systemd `MemoryPeak`    | 5.3 GB               |                             1.62 GB |
| DB file rewrites / 10 s | 5–9 (full file each) |                               **0** |
| `journal_mode`          | `delete`             |                               `wal` |
| sustained device writes | ~216 MB/s            | ~0 KB/s, peak 2 MB/s, `%util` 0.35% |

Two cheap confirmations:

- **`journal_mode` is a free tell.** sql.js does not use WAL. A WAL-mode database
  reporting `delete` with a 0-byte `-wal` sidecar is not on the native driver.
  After the fix, `-wal` grows normally (7 MB) — incremental writes.
- **`systemctl --user show <svc> -p MemoryPeak`** yields the old process's
  high-water mark for free, no historical monitoring required.

## Do NOT remove the performance workaround in the same change

A tmpfs RAM disk had been added earlier to absorb the write storm, and the user's
stated hope was to revert it as part of this deploy.

**Refuse that ordering.** Until the new build is running AND the native module is
confirmed mapped, the workaround is the only thing keeping the storm off the
volume. If the deploy is delayed or rolled back, removing it first converts a
survivable condition into an outage. Correct sequence:

1. deploy the fix
2. confirm the native driver is mapped in the NEW pid
3. confirm the rewrite rate collapses (count file-mtime changes over 10 s)
4. only then remove the workaround, re-measuring afterwards

Say this out loud with the reason. The user asked for the hack to come off and is
owed an explanation for why it stayed, not a silent deferral.

## A workaround changes what you are able to measure

While tmpfs is mounted the DB lives in RAM, so **host-level disk metrics
understate real demand**. `iostat` showed ~0 KB/s sustained and made the volume
look idle. The genuine load was the periodic persist sync, which had to be timed
directly:

```bash
X=$(awk '/nvme0n1 /{print $10}' /proc/diskstats); S=$(date +%s%N)
systemctl --user start <persist-sync>.service
E=$(date +%s%N); Y=$(awk '/nvme0n1 /{print $10}' /proc/diskstats)
# sectors/2 -> KB; then KB/ms -> MB/s
```

Result: **423 MB in 1.83 s = 231 MB/s**, every 3 minutes. Before recommending a
storage-throughput reduction, measure the BURST, not the average — an average of
2 MB/s would have justified cutting to the floor and clipping every sync.

## Attribute writes to the process, not just the device

`/proc/<pid>/io` separates the service's own writes from everything else:

```bash
sudo awk '/^write_bytes/{print $2}' /proc/<child_pid>/io   # sample twice, delta
```

Post-fix this read 25 KB/s for the router — evidence the storm was gone, not
merely relocated to another writer on the box.

## What the fix does NOT improve — predict it, then repeat it

Request latency was unchanged: p50 6,129 ms before vs 6,455 ms after, p95 ~38 s
both. That is upstream model generation (~30 ms/output-token for one provider,
~17 ms/tok for another), not router overhead. Providers returning in <800 ms
through the SAME router proved it was never the bottleneck. Only the GC-pressure
component improved.

**State this before the deploy and again after.** A user told "the memory fix
will help response times" will read unchanged latency as a failed deploy.
Separate "this fixes stability and disk I/O" from "this will not make the
upstream models faster; nothing on our side will."
