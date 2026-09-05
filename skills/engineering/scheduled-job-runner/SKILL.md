---
name: scheduled-job-runner
description: >
  Use when creating, migrating, debugging, or reviewing Hermes cron jobs. Ships a
  tested execution adapter for interpreter resolution, overlap prevention, hard
  timeouts, quiet success, structured ledgers, bounded redacted logs, failure
  notification, run severity, and heartbeat reporting.
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [cron, jobs, reliability, uv, pep723, alerting]
    related_skills: []
---

# Scheduled Job Runner

## Overview

Hermes cron remains the **scheduler**. `jobrun.py` is the execution adapter used
by each cron entry. Centralizing execution prevents every scheduled script from
reimplementing interpreter selection, overlap locks, timeout handling, output
policy, logging, and alerting differently.

The canonical implementation ships here:

- `scripts/jobrun.py` — execution adapter and CLI
- `scripts/jobrun_severity.py` — per-run outcome classification
- `scripts/jobrun_repair.py` — incident/dedup state and optional repair dispatch
- `scripts/generate_launcher.py` — filename-only cron launcher generator
- `tests/jobrun_*_checks.py` — standalone regression checks

Do not create another scheduler. Do not wrap jobs with tools that convert a child
failure into exit 0.

## When to Use

Use this skill when:

- adding or migrating a Hermes cron job;
- a job runs under the wrong Python or misses dependencies;
- success should be silent but failure must remain visible;
- overlapping or overlong runs are possible;
- an operator needs a durable run ledger rather than raw-output inference;
- a job appears successful while its output contains a real failure;
- a scheduler accepts only a script filename, not a command plus arguments.

## Install and Verify

Copy all three runtime modules together; `jobrun.py` loads its sidecars lazily
from the same directory.

```bash
mkdir -p "$HERMES_HOME/scripts"
cp scripts/jobrun.py scripts/jobrun_severity.py scripts/jobrun_repair.py \
  "$HERMES_HOME/scripts/"
chmod +x "$HERMES_HOME/scripts/jobrun.py"
python3 "$HERMES_HOME/scripts/jobrun.py" --selftest
```

The self-test starts real child processes and exits non-zero on any failed check.

## Job Specification

Specs live under `$HERMES_HOME/jobs.d/`:

```toml
job_id        = "daily-report"
script        = "daily_report.py"
runtime       = "auto"           # auto | uv | python | bash | command
timeout       = 300
overlap       = "skip"           # skip | allow | queue
output_policy = "silent"         # passthrough | silent
args          = ["--mode", "daily"]
owner         = "platform-team"
```

Validate without executing:

```bash
"$HERMES_HOME/scripts/jobrun.py" --spec daily-report --dry-run
```

A bare spec name always resolves through `$HERMES_HOME/jobs.d/`; a same-named
working-directory file or directory cannot shadow it.

## Generated Launchers Must Pin the Profile

Some Hermes cron configurations accept a script filename but cannot express
`jobrun.py --spec daily-report`. Generate a tiny launcher instead of resolving
`HERMES_HOME` dynamically:

```bash
python3 scripts/generate_launcher.py \
  --job-id daily-report \
  --profile-home /path/to/profile \
  --jobrun /path/to/profile/scripts/jobrun.py \
  --output /path/to/profile/scripts/run-daily-report.py
```

The generated script assigns `os.environ["HERMES_HOME"]` before executing
`jobrun.py`. This is required when the scheduler process belongs to another
profile; otherwise a bare spec name can resolve against the wrong `jobs.d`.

## Responsibilities

1. **Interpreter and dependency resolution** — including locked PEP 723 scripts
   via `uv run --locked --script`.
2. **Silence on success** — `output_policy = "silent"` suppresses routine output
   without suppressing failure cards.
3. **Overlap prevention** — advisory `flock` with skip, allow, or queue policy.
4. **Hard timeout and signal handling** — child process groups are terminated and
   reaped; timeouts and signals remain distinct outcomes.
5. **Structured JSONL run ledger** — each terminal row includes severity before
   it is persisted.
6. **Bounded, redacted logs** — capture is byte-bounded while the child runs.
7. **Heartbeat reporting** — best-effort start and terminal pings never alter the
   child outcome.

Bookkeeping must never kill a job. Ledger, notifier, heartbeat, and incident-state
failures are swallowed or reported without changing the terminal exit code.

## Terminal Exit Codes

Never collapse terminal states into exit 1.

| State | Exit | Meaning |
| --- | ---: | --- |
| `success` | 0 | Child completed successfully |
| `skipped_overlap` | 0 | Existing run still holds the job lock |
| `config_error` | 2 | Runner could not start the child |
| `child_failure` | 3 | Child exited non-zero |
| `timeout` | 4 | Deadline expired |
| `signal` | 5 | Runner received a signal |
| `wrapper_error` | 6 | Execution adapter failed |

## Severity and Noteworthy Runs

The child exit code establishes the severity floor. A final structured result
line may raise that severity but never lower a non-zero exit or override timeout,
signal, launch, or wrapper failures.

A spec can translate a child-specific exit convention:

```toml
[exit_map]
10 = "noteworthy"
20 = "degraded"
30 = "broken"
```

`noteworthy` means the job worked and found something worth reporting. It exits
0 from the wrapper, records a `job.noteworthy` event, and closes prior failure
conditions rather than leaving a stale incident open.

Failure detail selection scans both stdout and stderr for a failure-looking line.
A later successful cleanup line cannot replace the actual error in the incident
card.

## Ledger Concurrency Invariants

The append and prune paths share a separate `runs.jsonl.lock` file. They never
lock the ledger inode itself because pruning replaces the ledger path; inode
locking would allow an append to land on the old file and disappear.

Signal handlers call `append_ledger(..., blocking=False)`. `flock` is not
reentrant across file descriptors, so a blocking lock from a signal handler can
deadlock when the interrupted code already holds the prune lock.

The persisted `job.finished` row includes `severity` and `reason_code`. Compute
both before calling `append_ledger`; adding them afterward does not update JSONL.

## Output and Notifications

- `passthrough` preserves successful stdout byte-for-byte, including a trailing
  control payload.
- `silent` suppresses routine successful output.
- Failures always render an incident card.
- Optional `notify_target` sends the card directly with `hermes send --to`.
- `_v2_record_notification` records delivery truth so a failed notifier leaves
  the condition eligible to speak again.

Use placeholders in public examples:

```toml
notify_target = "<provider>:<destination>"
```

## Day-2 Commands

```bash
jobrun.py --list
jobrun.py --status daily-report
jobrun.py --failures 24
jobrun.py --bootstrap
```

The status API is `$HERMES_HOME/jobstate/runs.jsonl`. Do not infer health by
grepping raw job output.

## Python Dependencies

A Python job can declare and lock dependencies inline:

```python
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx"]
# ///
```

```bash
uv lock --script daily_report.py
```

Commit the generated lock. A PEP 723 header does nothing unless the script is
actually routed through `uv`; the adapter detects the block and uses the locked
runtime.

## Common Pitfalls

1. **Installing only `jobrun.py`.** Copy the severity and repair sidecars too.
2. **Generating an unpinned launcher.** It may use the scheduler's profile and
   resolve the wrong spec.
3. **Using the default timeout accidentally.** Make it shorter than the schedule
   interval, especially for consequential jobs.
4. **Locking `runs.jsonl` directly.** Prune replaces that inode; use the stable
   sidecar lock.
5. **Blocking in a signal handler.** Use the non-blocking append path.
6. **Computing severity after append.** The persisted row will silently omit it.
7. **Treating missing telemetry as zero.** Unknown is not a measured zero.
8. **Letting bookkeeping exceptions escape.** Observability must not change a
   job's outcome.

## Verification Checklist

- [ ] `python3 scripts/jobrun.py --selftest` passes.
- [ ] Every `tests/jobrun_*_checks.py` script passes.
- [ ] `--dry-run` reports the expected interpreter, argv, and profile spec.
- [ ] Success is silent when configured and failure remains visible.
- [ ] Terminal states retain their distinct exit codes.
- [ ] A persisted terminal row contains `severity` and `reason_code`.
- [ ] Concurrent append/prune checks lose no rows.
- [ ] Generated launchers pin `os.environ["HERMES_HOME"]`.
- [ ] No private hostnames, paths, IDs, or domain-specific integrations appear in
  committed files.
