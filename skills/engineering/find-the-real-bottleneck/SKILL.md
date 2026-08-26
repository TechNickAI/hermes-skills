---
name: find-the-real-bottleneck
description: >
  Use when something in a multi-layer stack is slow, memory-hungry, or expensive
  and you need to prove WHERE the cost actually originates before recommending a
  fix — a slow dashboard fronting a busy proxy, a request path spanning client →
  gateway → router → upstream API, a process whose RSS keeps climbing, a spend
  spike whose obvious explanation doesn't survive arithmetic. Enforces measuring
  each arrow in a causal chain rather than asserting a plausible mechanism, gives
  cheap discriminating tests (CPU-vs-wall, component-in-isolation, do-nothing
  probe, bypass test, sample-over-time), separates a failing subsystem that is
  the CAUSE from a downstream SYMPTOM, and refuses to call a fault "flake" before
  counting recurrence and comparing sibling hosts by version. Load before
  answering "why is X slow", "is it the database", "is DNS/the network bringing
  this box down", "was that just flake", or when about to blame GC, cache, table
  size, or RAM for a latency problem.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags:
      [performance, latency, diagnosis, capacity, profiling, devops, root-cause]
---

# Find the Real Bottleneck

**Mission:** prove where cost actually originates before spending money or effort
on it. The failure this skill prevents is not "wrong answer" — it's a _confident,
plausible, unmeasured causal story_ that drives a real recommendation.

## The Iron Law

```
DO NOT ASSERT AN ARROW YOU HAVE NOT MEASURED
```

Any sentence of the form `A → B → slow` contains claims. Each arrow is a
hypothesis until instrumented. Plausibility is the trap: a fabricated mechanism
survives your own review precisely because it _sounds_ like systems knowledge.

Before stating a cause, ask: **which of these arrows did I put a number on?**

### Tells that you are about to violate it

- "large tables → memory pressure → slow"
- "more RAM → less GC → faster"
- "the cache is cold, so it recompiles"
- "N concurrent users → contention → timeouts"

All four are reasonable. All four are testable in one command. Test them.

## Phase 1 — Bound the layers before blaming one

In a multi-tier stack (client → gateway → router → upstream), each layer must be
_excluded by evidence_, not by intuition. Cheapest exclusions first.

**Ask: did the traffic even go through the layer I'm blaming?**
Look for the request in that layer's own telemetry with its own identifiers.
If an agent's calls appear in the router's `usage_history` tagged with the
agent's key and endpoint, they went _through_ the router, not around it — which
exonerates any client-side fallback path in one query.

**Ask: did the fallback/alternate path fire at all?**
A configured fallback that never executed cannot be the cause. Count its rows.
Zero occurrences ever = ruled out, permanently, with one `COUNT(*)`.

**Ask: did the client even request the thing I'm blaming?**
Aggregate the _requested_ identifier (model, route, endpoint) from access logs.
If nobody asked for it directly, the selection happened server-side.

**Ask: did the instance I'm blaming actually emit this error?**
On hosts running several near-identical instances (fleet profiles, sibling
gateways, replicas), the error in front of you may belong to a _different_ one —
including your own. Before concluding "my fix didn't work," grep the failure
signature across every sibling's log, filter events by restart timestamp
(`awk '$0 >= "<restart ts>"'` — a tail does not prove recency), and check the
routing metadata for who the request was actually addressed to. Full worked case
and the "shipped default ⇒ fleet-wide blast radius" corollary:
`references/attributing-failures-across-sibling-instances.md`.

## Phase 2 — Cheap discriminating tests

Reach for these before profilers. Each isolates one arrow.

| Claim                                  | One-command test                                                        | Reading                                                            |
| -------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------ |
| "X inflates the heap"                  | `process.memoryUsage()` before/after doing X in isolation               | Flat = X is not in the managed heap at all                         |
| "It's CPU-bound (compile/GC/parse)"    | Δ(utime+stime) from `/proc/<pid>/stat` vs wall time                     | `cpu ≈ wall` = burning; `cpu << wall` = **queued or waiting**      |
| "It's cold-start / first-compile cost" | Hit a route that does NO work of the suspected kind — a 404, a redirect | If _that_ is also slow, the cost is not in the work you blamed     |
| "Component A is the bottleneck"        | Time A standalone vs the end-to-end path                                | A 2000x gap (0.002s query vs 5.8s endpoint) exonerates A instantly |
| "It's a leak"                          | Sample the metric 4x over 90s                                           | Flat = working set, not leak                                       |
| "It's load-dependent"                  | Sample latency _and_ concurrency together, 8x                           | Correlation with in-flight count beats any cold/warm story         |
| "Subsystem X is the cause"             | Exercise a path that **bypasses X entirely**                            | Bypass path also fails ⇒ X is a _symptom_, not the cause           |
| "It's random / a one-off"              | Count the signature per day across a 2-week window                      | A second occurrence makes it a pattern, not flake                  |
| "It's this host's fault"               | Same count on sibling hosts, grouped by version                         | Symptom tracks a version cohort ⇒ software, not hardware           |

**The do-nothing probe is the highest-value trick here.** A 404 on a nonexistent
static file executes no application code, touches no database, renders nothing.
If it takes 5.58s, the cost is upstream of everything you were about to profile.

**CPU-vs-wall accounting is the second.** It splits "working hard" from "waiting
in line," and those have completely different fixes.

## Phase 2a — Separate CAUSE from SYMPTOM with a bypass test

When a failure presents as "subsystem X is broken" (DNS, cache, auth, a queue),
the question is not _is X failing_ — it visibly is — but **is X the cause or a
downstream casualty**. Answer it with one test:

```
Exercise a path that does the same work WITHOUT X.
If that path fails too, X is a symptom.
```

Worked example. A machine's agent could not reach Telegram; the
logs were saturated with hostname-resolution failures, and the natural read was
"the home network's DNS is broken." The client, however, also retries against
**hardcoded fallback IPs** — a path needing no DNS at all. Those failed **659
times** in the same window. That single count reversed the diagnosis: nothing
could get out, so DNS was a casualty of a wedged network stack, not the cause.
No router, ISP, or resolver change would have helped.

Corroborating exclusions in the same pass, each one command:

- **A second, independent consumer.** Tailscale (own transport, no dependence on
  the LAN resolver) made **zero** successful TCP connections across the outage.
  One broken app is an app bug; two unrelated stacks failing is a layer problem.
- **Did the lower layer stay healthy?** Wi-Fi remained associated to the same
  SSID/BSSID and renewed DHCP every ~8 min throughout. Link was fine, so the
  fault sat above the link and below the apps.
- **Shared onset instant.** Graphics and networking both broke inside the _same
  minute_ and both recovered only at reboot. Two unrelated subsystems failing
  simultaneously is one upstream fault, not two coincidences.

**Consequence for remediation:** a fix aimed at the symptom is worse than no fix,
because it manufactures false confidence. A watchdog written to flush the DNS
cache and restart the resolver would never have helped here, and would have
looked like due diligence. When you overturn a cause, **re-derive every remedy
that was justified by the old story** and say plainly which ones are now void.

## Phase 2a-recurrence — Before calling anything "flake", count it

"Random one-off" is a conclusion, not a default. It requires the same evidence
as any other cause, and it is cheap to test:

1. **Count the signature per day over ≥2 weeks.** Here: `0,0,0,0, 226143, 0,0,0,0, 224080`
   — two enormous single-hour bursts against a zero baseline. Not flake; a
   recurring fault with a clean before/after story.
2. **Group sibling hosts by version.** The two hosts on the older OS build both
   showed the signature (one severe, one mild); the two on newer builds showed
   zero. A symptom that tracks a _version cohort_ rather than a machine points
   at software, and names the upgrade as the lever.
3. **Check what else happened at that timestamp.** Prior remediations clustered
   at the first burst revealed an earlier undiagnosed instance of the same bug.

**State the residual uncertainty explicitly.** Vendor release notes here were
security-only and named no matching fix, so the honest framing was "highest-value
available move, low risk, not a guaranteed fix" — plus a stated next lever if it
recurs. Verify the release actually exists on the channel you install
from before promising any upgrade outcome.

## Phase 2b — Establish the noise floor BEFORE reporting any A/B result

On network-attached storage (EBS/EFS/NFS) or any shared/virtualized host, I/O
latency jitter can exceed the effect you are trying to measure by 10x. A single
run is not a measurement — it is a sample from a wide distribution.

**Measured example (EBS gp3, same config, 5 alternating runs of 200 inserts):**

```
12 indexes: 7.76, 4.24, 0.78, 0.73, 0.78 ms   median 0.781
 9 indexes: 0.44, 0.43, 0.48, 2.39, 0.46 ms   median 0.455
```

Within-config spread is ~10x. Any single-run comparison here can "prove" either
direction, including the _reverse_ of the truth. One earlier single-run pass in
this same session produced "dropping 3 indexes made writes SLOWER" — pure noise,
which reversed on repeat.

**Protocol before you report an A/B number:**

1. Run each arm **≥5 times, alternating** (A,B,A,B,…) so drift affects both arms.
2. Report the **median**, and show the raw runs so the spread is visible.
3. If within-arm spread ≳ between-arm difference, the honest answer is
   **"no measurable effect"** — say that rather than picking the flattering run.
4. Rebuild fresh state per trial (fresh DB copy, cleared cache) so trial N isn't
   inheriting trial N−1's warmed pages.

**Corollary — retract noisy numbers you already reported.** If earlier claims in
the same session came from single runs, name them explicitly as unreliable when
you correct them. Do not silently replace one number with another; the operator tracks
the claims and will notice the contradiction before you do.

### Separate the variables you are conflating

The `A vs B` you set up often changes two things at once. In the index test,
"empty table + 12 indexes" vs "245k rows + 0 indexes" varies **both** row count
and index count — so the result cannot attribute cost to either. Vary exactly
one dimension per trial:

| Question                     | Hold constant      | Vary                 |
| ---------------------------- | ------------------ | -------------------- |
| Do indexes cost writes?      | row count, pragmas | index set            |
| Does table size cost writes? | index set, pragmas | row count            |
| Is it fsync?                 | rows, indexes      | `synchronous` pragma |

The fsync test is usually the decisive one, and it is one pragma:
`synchronous=OFF` 0.066ms vs `NORMAL` 5.017ms vs `FULL` 14.548ms per insert
means the cost is **durability barriers, not CPU and not schema**.

## Phase 2c — Validate → change ONE thing → re-validate

When the user asks to actually _fix_ infrastructure ("bump it and confirm it
worked"), the deliverable is a **before/after pair from an identical harness**,
not a plausible argument that the change should help.

```
1. Write the benchmark as a SCRIPT (not ad-hoc commands) so both runs are identical.
2. Run it -> BASELINE. Save the numbers.
3. Change exactly ONE variable.
4. Run the SAME script -> AFTER.
5. Diff. If it didn't move, say so and revert.
```

Use `scripts/storage_perf_baseline.sh` for storage/latency work — it emits
`KEY=VALUE` lines specifically so two runs diff mechanically.

**Measurements go stale — re-baseline immediately before proposing a change.**
Same host, same volume, hours apart in one session: fsync p50 was **77ms**, then
**1.03ms** after an unrelated DB cleanup and restart. Any remediation argued from
the stale figure would have targeted a bottleneck that no longer dominated. If
your measurement is more than a few hours old, or _anything_ changed in between,
re-measure before you spend money.

**Verify units before believing a saturation claim.** Cloud metrics are often
period _sums_, not rates. See the unit-trap section in
`references/sqlite-write-path-on-network-storage.md` — reading EBS
`VolumeWriteOps` as a rate produced "7–10x over the IOPS cap" when the true
utilization was **14%**, and would have bought the wrong resource.

## Phase 2d — Before optimizing a cost, ask whether it should exist at all

A saturated resource has two fixes: **raise the ceiling** (costs money) or
**stop generating the load** (usually free, and usually correct).

Always compute whether the observed load is _reasonable_ for the work being done:

```
service writes: 82 MB/s sustained
DB file growth: 0.02 MB/s
insert rate:    0.1 rows/sec
```

82 MB/s to persist 0.1 rows/sec is not a capacity problem — it is a **write
amplification bug**, something rewriting the same pages continuously. Provisioning
more bandwidth would pay monthly to move the same wasted bytes faster.

**State this explicitly before recommending a paid upgrade**, and offer the
diagnosis path as an alternative: "this may eliminate the need for the spend
entirely — want me to chase it first?" Let the user choose with the tradeoff
visible.

## Phase 3 — Distinguish managed from unmanaged memory

Do not read RSS and conclude "GC pressure." Break it down:

```
rss           2313 MB   total process
heapTotal      668 MB   V8 heap reserved
heapUsed       540 MB   <- the ONLY thing GC manages
external      1194 MB   C++ objects tied to JS
arrayBuffers  1092 MB   raw buffers (in-flight stream payloads)
```

If `arrayBuffers` dominates, the memory is **working set of in-flight work**, not
collectable garbage. Raising a heap cap will not reduce it, and it is not a leak.

**Native libraries do not touch the JS heap.** SQLite (better-sqlite3), image
codecs, and compression libs count rows and buffers in C. Measured directly:
20 queries against a 245,000-row table moved `heapUsed` 3.6 MB → 4.1 MB and
`external` not at all. Table size cannot influence JS garbage collection. Any
"big tables → GC → slow" chain is false by construction.

## Phase 4 — Amplification arithmetic for cost spikes

When spend spikes, resist "the errors caused it." Divide.

```
ignition events (distinct root causes): 6
resulting expensive calls: 452
amplification: 75x per ignition
```

If a handful of events produced hundreds of expensive calls, the story is **not**
the events — it's the mechanism that turned each one into many. Fix the
amplifier, not the trigger. Find the ignition count from state tables (which
sessions/keys got stuck), not from the error log.

Also: **compare by tokens and cache-hit rate, never by call count.** Identical
work at 0% cache read versus 86% differs ~7x in cost. Volume can be flat while
spend explodes.

## Phase 4b — Check whether your "fix" can even survive

A fix that silently reverts is worse than no fix: it consumes trust and produces
a false all-clear. Before proposing _or_ applying a remediation, ask what will
undo it.

**Live-process page cache overwrites external writes.** A long-running process
holding a SQLite DB open with a large page cache (`cache_size = 65536` = 64 MB)
treats its in-memory pages as authoritative. An external `DELETE` + commit lands
on disk, then the process's next write flushes its **stale cached pages** over
your change. Symptom: the delete reports `changes=22515`, reads back as `0` in
the same connection, and is fully restored seconds later from a new connection.

Decisive test — delete rows the live process **cannot** be creating (e.g. dated
two weeks ago). If those come back, it is not re-insertion, it is page-cache
overwrite:

```
Jul-20 rows: 22515 -> 0  (deleted 22515)
after 6s, Jul-20 rows: 22515   <-- restored
```

`wal_checkpoint(TRUNCATE)` makes it _briefly_ visible, which is a red herring —
it still loses the race. The only reliable paths: **stop the process**, mutate,
restart (verified: 342,696 rows deleted, VACUUM 521 MB → 358 MB, ~75s downtime,
survived restart); or make the change **through the owning process**.

**Schema mutations re-apply on every boot.** Before recommending "drop this
index," grep for `CREATE INDEX IF NOT EXISTS` in whatever the startup path
executes. If the app runs a `SCHEMA_SQL` blob at boot (`db.exec(SCHEMA_SQL)`),
any index defined there is **recreated on every restart** — a drop is not a
config change, it's a source edit requiring a build. Distinguish:

- defined in `SCHEMA_SQL` / boot path → self-heals every start, needs source edit
- defined in a numbered migration → applied once, tracked in a migrations table

**Generalize:** for each proposed fix, name the mechanism that could revert it —
boot-time schema re-application, config hot-reload, deploy overwriting the built
artifact, a cron re-sync, or another writer's cache. If you cannot name it, you
have not checked.

## Phase 5 — Re-derive recommendations when the mechanism changes

A wrong mechanism produces a wrong recommendation, and correcting the sentence is
not enough. **Walk back every downstream conclusion.**

Worked example: "big heap → GC thrash" made _more RAM_ look like the fix. Once
the real mechanism was known (single-threaded event loop saturated by concurrent
streams), the advice inverted — Node will not use extra cores for the main event
loop, so more vCPU **cannot** fix a saturated single thread. The heap bump was
still right for preventing OOM _crashes_, but was never going to touch latency,
and had been implied to.

**Before recommending a machine resize, compute the ceiling of the win:**

```
router overhead (warm)     2.4 ms
upstream LLM (avg TTFT) 16,130 ms
=> router is 0.015% of a request
```

If the layer you'd be upgrading is a rounding error in the total, say so and
decline the spend. Name the price of the thing you're declining
(`+$66/mo for 0.015%`) — it makes the recommendation concrete and checkable.

## Reporting the result (the operator's preferences)

- **Lead with the measurement, not the narrative.** Numbers first, mechanism
  second.

### When the user floats several remedies at once, TRIAGE — don't answer serially

the operator will often fire a burst of candidate fixes in one message ("more RAM? faster
disk? NVMe? DB in RAM? what else?"). Answering them one at a time as they arrive
produces contradictory advice across turns, because each answer is argued from
whatever was measured most recently.

His explicit instruction: _"be systematic about triaging my ideas and validating
them. keep a list so you get to examine them, and then make a recommendation."_

Do this:

1. **Write the list down** (todo tool) with one row per idea, including ideas you
   already doubt — they still need a stated verdict.
2. Measure or reason each to a verdict: **validated / ruled out / needs a test /
   deferred**, each with the number that decided it.
3. Deliver **one** ranked recommendation at the end, cheapest-and-most-certain
   first, with cost attached.
4. If he asks for it to be multi-reviewed, do that before presenting.

Answering out of order is acceptable when he explicitly reprioritizes ("drop the
index idea for now", "stop, come back to that later") — record the deferral in
the list rather than dropping it silently.

### Distinguish "I ran the app's routine" from "I wrote my own"

the operator asked pointedly: _"Did you actually run the data clean up script, or delete
things on your own? What actually got deleted."_ If you reimplemented the app's
logic instead of invoking it, **say so unprompted**, and name what your version
covers versus what the real one does (here: 3 tables hand-written vs 12 in
`runAutoCleanup`). Silently substituting your own implementation and calling it
"the cleanup" is the thing to avoid.

- **Retract plainly when wrong.** "I was wrong. I claimed X and never verified
  it. I tested it directly and it doesn't hold. Here's the measurement, and
  here's what changes about my recommendation." Do not re-explain the old theory
  louder; do not smuggle the correction into a paragraph about something else.
- **Distinguish what you proved from what you couldn't.** "Root cause is still
  UNKNOWN. Ruled out: A, B, C, D, E" is a legitimate, valuable deliverable.
  Never invent an explanation to fill the gap.
- **Say when an action failed.** If a fix didn't persist or a job rolled back,
  report it as a failure with evidence — do not let a successful-looking command
  exit stand in for a verified outcome.
- the operator pushes back with "this doesn't sound right" / "that seems terrible" when a
  mechanism is hand-waved. Treat that as a signal to **measure**, not to
  re-argue.

## Common Pitfalls

- **Sampling quiet moments and calling it "cold vs warm."** Under bursty load,
  latency is noisy. Always sample alongside a concurrency metric before claiming
  a cache/cold-start pattern.
- **Reading one RSS value and declaring a leak.** Sample over time first.
- **Trusting `.timer on` / exit codes as proof of effect.** Read the value back.
- **Blaming the database because the endpoint is slow.** Time the query directly;
  it is usually milliseconds.
- **Assuming a config knob is the cause without reading the consumer.** A setting
  gated on input the client never sends is inert.
- **Treating a subagent's conclusion as evidence.** Verify its artifacts
  yourself; a timed-out subagent may still have done correct work, and a
  confident one may have theorized. See
  `references/verifying-delegated-work.md`.
- **Declaring a mutation successful because the command reported changes.** A
  live process holding the same file can silently revert your write. `DELETE`
  returning `changes=22515` proved nothing — the rows were back 6 seconds later.
  Re-read from a **new connection after a delay**, and prefer a control that the
  running app cannot legitimately touch (e.g. delete rows dated two weeks ago;
  if _those_ come back, a process is overwriting you, not racing you).
- **Proposing the next capacity tier when the last one was instantly consumed.**
  If a paid bump is re-saturated within minutes (250 MB/s provisioned → 217 MB/s
  used), the workload has an amplification bug. Buying more capacity converts a
  bug into a subscription. Name the unexplained amplification instead.
- **Repeating an error string's own wording as your diagnosis.** SQLite reports
  a missing _module_ as `no such table: dbstat`. Echoing that verbatim sent the
  user straight to "did we miss a migration?" — an impossible cause, because
  `dbstat` is a built-in virtual table that no migration creates and that never
  appears in `sqlite_master`. Before repeating an error noun, confirm what the
  object actually **is**: schema object, virtual table, view, or extension.
  `SELECT COUNT(*) FROM sqlite_master WHERE name='<x>'` returning 0 for a table
  you can successfully query is the tell that it is virtual/compiled-in, so the
  real question becomes _which connection lacks the module_, not _which
  migration failed_.
- **Concluding "it works" from a probe that used a different engine than the
  server.** A service may open its DB through a driver cascade
  (`better-sqlite3` → `bun:sqlite`/`node:sqlite` → **sql.js WASM fallback**).
  Ad-hoc CLI probes always land on the native driver and pass; the running
  process may be on the WASM build, which ships without optional vtabs like
  `ENABLE_DBSTAT_VTAB`. Testing both the checkout's module _and_ the deployed
  bundle's module still proves nothing if neither is what the server chose.
  Instrument the live process to report its actual driver before theorizing —
  and until then, say the mechanism is unconfirmed.

  The driver choice can itself explain whole-file write amplification. A sql.js
  persistence adapter may implement each flush as `db.export()` followed by
  `writeFileSync(databasePath)`, rewriting a database-sized byte count whenever
  dirty state is saved. Corroborating signature: live startup logs show native
  drivers failed, process `write_bytes` advances by approximately the main DB
  size per burst, the DB size remains flat, and the WAL remains at zero. That is
  materially stronger than blaming cache size or checkpointing. The remediation
  is to package and prove the native SQLite module in the actual deployed
  runtime, then compare write counters under an identical workload.

  **CONFIRMED later** — the mechanism above is no
  longer a hypothesis. Three independent signals on the live process:
  1. `grep better_sqlite3.node /proc/<pid>/maps` → **0 matches** (only unrelated
     native modules mapped), so the native driver was never `dlopen`ed.
  2. Startup logs said it outright:
     ```
     [DB] Sync driver 'better-sqlite3' failed to open: Cannot find module 'better-sqlite3'
     [DB] Sync driver 'node:sqlite'  failed to open: Cannot find module 'node:sqlite'
     [DB] Pre-initializing sql.js WASM (synchronous drivers unavailable)...
     ```
  3. File mtime advanced 5–9 times per 10s on a 438 MB DB ≈ **216 MB/s** of
     whole-file rewrites, with `journal_mode=delete` and a 0-byte `-wal`.

  **Get the log line before doing `/proc` forensics** — it is one `journalctl`
  grep for `Sync driver|sql.js|Pre-initializing` and it is unambiguous, whereas
  a maps-grep only tells you what is absent. Also: the prebuilt binary _was_
  present on disk at `node_modules/better-sqlite3/prebuilds/linux-arm64.node`,
  which confirms the fault is the webpack-stubbed `require`, not a packaging
  gap. **Never conclude "the module is missing" from a file-existence check.**

  **The same bug also presents as a memory leak.** sql.js holds the entire DB in
  memory and re-serializes it, so external/arrayBuffer memory tracks DB size.
  Here a watchdog was restarting the service on a ~12h cycle for "memory crisis"
  (RSS 4.32 GB vs 1.46 GB baseline, external buffers 33x baseline) — four times
  in 72 hours. Write amplification and the leak were **one root cause**. If a
  watchdog is papering over recurring restarts, check the driver before accepting
  the leak as independent.

- **Citing an INHERITED diagnosis as if you had proven it.** A root cause you
  read in a PR description, an issue thread, a colleague's writeup, or your own
  earlier session note is a _hypothesis you did not test_. On one occasion I
  asserted "the bug has already been identified" three times across a session,
  sourced entirely from a PR body. the operator challenged it — _"what do you mean the
  bug has already been identified?"_ — and the verification pass proved the
  mechanism was real but **my description of it was wrong**: I had said webpack
  "stubbed the require," when it had actually replaced the _injectable loader
  itself_, a different defect with a different fix. The claim was directionally
  lucky and specifically wrong.
  **Rule:** before repeating someone else's root cause, either verify it against
  the live artifact or label it explicitly (\"per PR #10, unverified by me\").
  Attribute the source out loud so the user can weigh it. A borrowed diagnosis
  repeated confidently becomes indistinguishable from a measured one within two
  turns, and _you_ will be the one who defends it.
- **Letting an alert's stated root cause frame your investigation.** A watchdog
  page that says \"NOT a JS heap leak, likely C++ addon or streaming buffer\" is
  a _guess by a small model with less context than you_, formatted like a
  finding. Here it was half right (not the heap) and half wrong (not a streaming
  buffer), and it had driven four escalations hunting a nonexistent leak. Read
  the alert for its **measurements** (RSS, timestamps, rate) and re-derive the
  cause yourself. When an automated escalation is chasing a cause you have
  disproven, say so plainly and recommend stopping it — repeated escalations to
  an expensive model cost real money.
- **Reading a guarded call and assuming its neighbours are guarded too.** A
  codebase that wraps `COUNT(*)` in `try/catch` filtering
  `"no such module:"` demonstrates upstream _already knows_ optional modules go
  missing — yet the very next line's `dbstat` query sat outside that guard, so
  one unavailable module 500'd the whole settings API. When you find a defensive
  guard, check every sibling statement in the same loop; an inconsistent guard
  is a stronger, more portable bug report than the environment-specific cause,
  because it is correct regardless of which driver is in play.

## Phase 2e — Hardware premises get measured, not honored

A standing belief about hardware ("this box needs NVMe, it reads so many small
files") is an unmeasured arrow wearing a hardware costume. It is stickier than
most because the workload really _is_ I/O-shaped — an agent genuinely does run
tens of thousands of terminal calls and file reads a month. But **a workload
being I/O-shaped is not evidence that I/O is the constraint.** Nobody measures
it, because the box feels fine and nothing errors, so the belief survives for
months and then quietly drives a hardware purchase.

Compare observed-vs-provisioned at _percentile_ resolution over a window that
includes the busiest period; daily averages hide exactly the spike being
claimed. On the co-tenant host this took one probe and returned p50=45 IOPS against a 6000 IOPS
provisioned budget — premise dead, three orders of magnitude of headroom.

Two readings people get wrong: `VolumeQueueLength` >1 is the real saturation
signal (requests actually waiting on disk), not raw IOPS; and check what is
_already_ provisioned before proposing an upgrade — the co-tenant host's root was already gp3
at 6000/250 and already NVMe-attached, which dissolves most "move to NVMe"
arguments on the spot.

Then keep going: killing the premise does not answer the question. Run the other
axes (RAM, CPU, disk _space_, co-tenancy, base-image cruft) and **reframe the
decision around the constraint you actually found.** the co-tenant host's real problems were
memory pressure and an agent sharing `/home/ubuntu` with a public web tier and
two databases. A hardware question can have an isolation answer; say so
explicitly rather than answering "no" and stopping.

Full method, the caveat-on-your-own-window habit, and the "name the cheap fix
you are declining" move: `references/falsifying-a-hardware-premise.md`.

## Phase 2d — When the numbers don't add up, say so and stop

If observed I/O is orders of magnitude larger than the data actually changing,
you have an unexplained amplification and **no license to name a cause**.

Worked example: the process wrote ~197 MB/s while the DB stayed at 334 MB, the
WAL file never left 0 bytes, `app.log` grew 19 KB in 20s, journald grew 0 KB, and
inserts ran at 0.1 rows/sec across 53 requests in 3 minutes. Roughly 10,000x more
disk writes than data stored. Checkpoint thrash was the natural theory — the flat
WAL falsified it.

The right move is to state the arithmetic, list what you ruled out, and say the
mechanism is unknown. Do **not** let a plausible-sounding candidate fill the gap
just because the user is waiting on an answer. If the user-visible symptom is
already fixed by other means, recommend parking it _and flag it as genuinely
unexplained_ rather than quietly dropping it.

Also beware **measurement artifacts inside the anomaly**: one sample showed
`storage.sqlite` growing 278 MB in 20s, which would have been a completely
different (and wrong) story. Re-reading the file size showed it stable at 334 MB.
Confirm a shocking delta with a second, independent read before building on it.

## References

- `references/infrastructure-sizing-and-platform-first-specs.md` — **read before
  recommending a size, an instance type, or a tool for NEW infrastructure.** The
  same discipline applied forward instead of backward. Padding a spec is an
  unpriced tax: measuring took two commands and cut 8 GB→4 GB, 60 GB→30 GB,
  ~$73→~$28/mo. Carries the `ps %CPU` lifetime-average trap and the
  `/proc/<pid>/stat` delta loop that finds short-lived respawns `top` misses (a
  box "pinned at 0 CPU credits" turned out to be a legacy health check consuming
  the box it monitored — my own cautionary example was invalid). Also: check
  what the platform you already pay for ships before reaching for a third-party
  tool (Amazon DCV is free on EC2 with a native Apple-Silicon client); prove
  vendor artifacts with range-GETs and container manifest platforms rather than
  marketing pages (`kasmweb/*` is x86_64-only, all 68 tags); pull pricing live
  per candidate; and name the dominant cost line even when it is not the one you
  were asked about.
- `scripts/ebs_saturation_probe.py` — **runnable** verdict on "is storage the
  bottleneck": provisioned-vs-observed IOPS/throughput/queue-length percentiles
  from CloudWatch, chunked by day to dodge the 1440-datapoint cap, reading
  provisioned values from the EC2 API so you never compare against the wrong
  baseline. Exits non-zero on an empty series rather than reporting "0 samples"
  as low load.
- `scripts/agent_workload_profile.py` — **runnable** profile of what a Hermes
  agent actually does, from `state.db`: tool histogram (the agent's kind), cwd
  distribution (the working set that sizes the box), source/subagent fan-out,
  and models. Handles the epoch-float timestamp trap.
- `references/falsifying-a-hardware-premise.md` — **read before honoring any
  standing hardware belief** ("this box needs NVMe, it reads so many small
  files"). A workload being I/O-shaped is NOT evidence that I/O is the
  constraint. Compare observed-vs-provisioned at PERCENTILE resolution over a
  window covering the busiest period — daily averages hide the exact spike being
  claimed; on the co-tenant host, p50=45 IOPS against 6000 provisioned killed the premise in
  one probe. `VolumeQueueLength` >1 is the real saturation signal, not raw IOPS.
  Check what is ALREADY provisioned (the co-tenant host's root was already gp3 6000/250 and
  already NVMe-attached). Then run the other axes — RAM, CPU, disk _space_,
  co-tenancy, base-image cruft — and reframe the decision around the constraint
  you actually found: a hardware question can have an isolation answer. Also
  carries the state.db epoch-float timestamp trap, the absurd-cost-telemetry
  sanity check, the CloudWatch 1440-datapoint cap, and the write_file→scp→ssh
  shape that gets an audit script past the lifecycle guard.
- `scripts/storage_perf_baseline.sh` — **runnable** before/after harness for
  storage-bound latency work: volume config, fsync percentiles, `dd` vs
  provisioned throughput, 5-trial median SQLite insert, live disk write rate,
  and 12-sample endpoint latency. Emits `KEY=VALUE` lines so a BASELINE run and
  an AFTER run diff mechanically. Run it, change one variable, run it again.
- `references/measurement-recipes.md` — copy-paste probes for CPU-vs-wall, heap
  isolation, do-nothing routes, load correlation, and amplification arithmetic.
- `references/sqlite-write-path-on-network-storage.md` — measured fsync/pragma/
  index numbers for a synchronous-SQLite service on EBS, why a blocking write
  stalls an entire Node event loop ("0-CPU freeze"), a full `synchronous`
  durability table for recommending OFF vs NORMAL vs FULL, **EBS CloudWatch
  IOPS/throughput saturation checks with copy-paste aws-cli commands**, gp3
  cost math, and a remediation menu ordered by measured leverage.
- `references/case-study-router-pinning-and-dead-code.md` — worked examples of
  Phase 4/4b: a 75x cost amplification traced to 6 pinned sessions, a scheduler
  that is written+called but lives in a never-imported module (and the
  one-command log check that proves it), mutations silently reverted by a live
  process's page cache, and schema drops that self-heal on boot.
- `references/mutating-a-live-sqlite-database.md` — **why external deletes
  revert** (the live process's 64 MB page cache flushes stale pages over yours),
  the only reliable stop→mutate→VACUUM→start sequence with measured downtime,
  how to keep the outage window minimal (online backup while running), the
  per-table column/format gotchas that make a purge silently delete 0 rows, and
  how to schedule this as an agent-driven recurring job.
- `references/verifying-delegated-work.md` — how to audit a subagent's output
  when it times out or self-reports success.
- `references/attributing-failures-across-sibling-instances.md` — when several
  near-identical instances run on one host or channel, proving WHICH one emitted
  the error before re-diagnosing: cross-instance log grep, restart-timestamp
  filtering, routing metadata, and why a framework-shipped default means the
  diagnosing agent is exposed too.
- `references/router-vs-upstream-latency-attribution.md` — **read when an owner
  asks "users say it's slow, is it my proxy/router/gateway?"** Four probes
  cheapest-first: the proxy's own no-upstream endpoint, the FAST-PROVIDER
  CONTROL in the same dataset (the strongest evidence there is — sub-second
  gemini/cohere through the same code path exonerates the router), per-output-
  token normalization that separates "long answer" from "slow generation", and a
  multi-day per-model baseline that tests whether today is anomalous at all.
  Carries the ISO-string-timestamp trap that made every time window return
  identical numbers, the retention-cap-looks-like-a-window trap, and the
  reporting shape for an honest "mostly no, but partly yes".
- `scripts/router_latency_attribution.cjs` — **runnable** implementation of the
  above against a router `call_logs` table, including the torn-read retry loop
  required to read a live sql.js-backed SQLite file.
- `references/retiring-a-performance-workaround.md` — **read when a hack
  (RAM disk, cache tier, raised capacity) was installed to survive a bug that has
  since been fixed, and someone asks "do we still need this?"** The trap is
  asking "is the workaround faster?" — it usually IS (measured 3.9x here) and
  that is the wrong question. The right one is whether the difference matters at
  real demand: 10,099x headroom on the slow option, +0.033 ms per request,
  0.0005% of p50. Covers the interleaved A/B protocol, peak-minute demand
  measurement, separating in-request from background cost, pricing what the hack
  costs to keep, symlink/timer/unit traps during migration, proving the new path
  is in use via `/proc/<child-pid>/fd`, and refusing to claim a latency win the
  measurement does not support.
- `scripts/bench_storage.cjs` — **runnable** A/B storage benchmark modeling a
  real DB write mix (inserts + upserts + reads + WAL checkpoints) rather than
  `dd`. Emits `KEY=VALUE` lines; run interleaved across both backends.
