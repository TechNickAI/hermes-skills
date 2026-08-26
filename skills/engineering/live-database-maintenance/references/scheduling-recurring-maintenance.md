# Scheduling a recurring stop-mutate-start maintenance job

Field notes from converting a hand-run SQLite retention clean into a weekly
agent-run job. Companion to the "Scheduling this as a recurring job" section in
SKILL.md.

> ⚠️ **Scope: this file is about maintenance that STOPS THE SERVICE.** Retention
> that only deletes rows does not, and the rules below invert for it — see
> "When the work does NOT stop the service" immediately after this. Applying the
> off-host agent-driven design to plain retention produces a centralized runner
> nobody needs and a cross-host permission problem nobody asked for.

## When the work does NOT stop the service

Row-level retention is short transactions against a live database. Nothing is
stopped, so the reasoning below about dying between stop and start does not
apply. Measured facts that invert each rule:

- **A profile CAN maintain its OWN store from inside its own runtime.** A
  lifecycle guard that blocks a service restarting itself does not block
  retention, because retention stops nothing. Verify the constraint against the
  real thing before designing around it — an assumed constraint produced a
  needless central-runner design.
- **Prefer a `no_agent` SCRIPT over an agent turn.** No LLM, no tokens, and a
  deterministic silence contract (empty stdout = nothing delivered). Reserve an
  agent for work that genuinely needs judgement at a failure point.
- **Install PER TARGET, not one job reaching across hosts.** A scheduler that
  SSHes into every member concentrates credentials and failure into one box.
  Each member runs its own copy against its own store.

The off-host, agent-driven design in the rest of this file remains correct for
sequences that actually take the service down.

## Rolling one job out to every member

Ship an **installer script that runs ON each host** and walks that host's own
profiles, rather than a central loop that reaches out. It should:

- copy the scripts into each profile's own directory and byte-compile them
- register the job idempotently **by name** (replace, never append a duplicate)
- **stagger co-tenant profiles** by a fixed offset so two on one host never
  contend for the same disk
- back up the job file before rewriting it

Then verify by re-reading each target's stored config. Two traps that make a
correct rollout look broken:

- **A freshly registered job reads back a null next-run time.** The scheduler
  fills it in on its next tick, tens of seconds later. Re-read before
  concluding the registration failed.
- **`grep -A<n>` around a job name bleeds into the following record**, showing a
  time that belongs to a different job. Read the stored value, not scraped
  console output.

Schedules land in each host's **own local timezone**, which is usually what you
want for "4am": it means 4am where that owner lives. Confirm rather than assume,
and state it explicitly when reporting.

## Why an agent and not a bash cron

_(For the stop-mutate-start case only — see the scope note above.)_

The sequence stops production. A shell script that dies between "stop" and
"start" leaves the service down with nobody home. The recovery invariant in
SKILL.md — read the journal, retry, preserve the broken DB, restore the verified
backup, re-verify health — is only meaningful if something can reason at the
failure point.

Schedule the agent on a machine that is _not_ the target host, so a target-host
problem cannot take out the thing meant to repair it.

## Downtime accounting from a real run

```
backup created: storage.sqlite.preclean-<ts> 353 MB 19:10:36 UTC
service stopped: ~19:11:0x UTC
service started (healthy): 19:11:37 UTC
```

Backup ran ~30s while serving traffic. Actual outage was the stop→healthy gap,
well under a minute. An earlier hand-run of the same work, with the backup taken
_after_ the stop, cost ~2.5 minutes. Same operations, ~4x the outage, purely from
ordering.

## Prompt elements worth grepping for after registration

Read the stored prompt back out of the scheduler's `jobs.json` and confirm each
of these appears. A creation call returning success tells you nothing about what
was actually stored.

```
stop service systemctl --user stop <svc>
prove process gone pgrep -f '<fingerprint>'
online backup (taken BEFORE stop)
abort on bad backup ABORT / do not proceed on an unverified backup
checkpoint wal_checkpoint
compaction VACUUM
restart systemctl --user start <svc>
health poll <health URL>, HTTP 200 required
library choice app's own SQLite binding, not the CLI
transient-read retry retry loop on 'malformed'
timestamp gotchas per-table column + format contracts
recovery diagnose journalctl
rollback restore verified backup
build prohibition never build/release on the live host
```

A one-line Python check over `jobs.json` that prints OK/MISSING per item catches
a truncated or paraphrased prompt in seconds.

## Scheduler behaviour that destroyed a job

Observed with a `repeat: once` job whose fire time had already passed:

```
cronjob action=run -> executed: true, execution_success: false
                        job disappears from jobs.json
                        target host untouched — nothing ran
```

The trigger consumed the expired one-shot instead of executing it. Net result:
no maintenance, no job, and the only copy of a 10 KB prompt gone.

**Do this instead:** create the real recurring schedule first
(`0 9 * * 0` — Sunday 09:00 local, low traffic), _then_ trigger a validation run
against it. A recurring job survives being fired, and the test exercises the
exact artifact that will run unattended.

**Before recreating anything**, look for the prompt in the authoring agent's
scratch space (`/tmp/*-prompt.txt`) and its live delegation transcript. Rewriting
a long safety-critical prompt from memory loses detail exactly where it matters.

## Verifying the run actually happened

`last_status: ok` means the agent's turn completed. It does not mean the
maintenance succeeded. Confirm on the target host:

```
service active + process present
health endpoint 200
DB size changed as expected
fresh backup file with the expected timestamp
service start time matches the run window
```

If the job was configured to deliver a report and none arrived, report that gap
explicitly. Host-side evidence proving the work happened is not evidence that the
notification path works — those are two separate claims.

## Backup hygiene

Each run wrote ~350 MB. A weekly job with no pruning adds ~18 GB/year to the
volume you were trying to keep healthy. Prune in post-flight (while the service
is running): delete beyond N days, always keep the most recent few regardless of
age, and report what was reclaimed.
