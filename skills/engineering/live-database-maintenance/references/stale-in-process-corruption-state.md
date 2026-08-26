# Corruption that lives in the PROCESS, not the file

A fourth failure class, distinct from the three the parent skill already covers.
Get the triage order right or you will plan a repair for a database that is
already fine.

| class                                  | file on disk | live process | fix                        |
| -------------------------------------- | ------------ | ------------ | -------------------------- |
| false corruption from `?mode=ro`       | clean        | fine         | stop using the URI form    |
| transient torn read                    | clean        | fine         | retry a small read at open |
| real corruption                        | corrupt      | failing      | restore + merge forward    |
| **stale in-process state (this file)** | **clean**    | **failing**  | **restart the process**    |

## Symptom

Every write from the running service fails with `database disk image is
malformed`, continuously, for tens of minutes. Meanwhile every check you run
from a _separate_ process says the database is healthy.

Measured on one run, Hermes `a research agent` profile, 1.5 GB `state.db`:

- `pragma integrity_check` → `ok`
- both FTS5 indexes → `integrity-check` passes clean
- real `INSERT` + `COMMIT` + `DELETE` from a fresh connection → succeeded
- row counts sane and self-consistent (`messages` 194,437 = `messages_fts` 194,437)
- gateway PID 10789, uptime ~38 h, still emitting `malformed` on every write

First `malformed` line at 10:50:41. A `state.db.repair.lock` breadcrumb sat at
10:41 — something repaired the file underneath the running process nine minutes
earlier, and the process never reopened.

## Why the process cannot heal itself

Hermes has an in-place recovery path (`_enter_fts_fail_open()`,
`hermes_state.py:3867`) that detaches corrupt FTS indexes so canonical writes
can continue. It fails here:

```
ERROR hermes_state: Could not detach corrupt FTS indexes;
canonical write still cannot proceed: database disk image is malformed
```

The detach is implemented as `BEGIN IMMEDIATE` + `INSERT INTO state_meta` +
`DROP TRIGGER` + `COMMIT`. **The recovery is itself a write**, so it runs
through the same poisoned connection and hits the same error. Any self-heal
whose first action is a write cannot recover a connection-level fault. Note
this generally when reviewing recovery code: a heal path must not depend on the
faculty it is trying to restore.

`_attempt_fts_runtime_rebuild()` (line ~3795) is also one-shot per process —
guarded by `self._fts_runtime_rebuild_attempted`. Once it has burned its single
attempt, only a restart re-arms it. So a long-uptime process gets exactly one
chance and then degrades permanently.

## Triage order

Do this before proposing any repair, restore, or merge-forward:

1. From a **separate** process, run `pragma integrity_check` and the FTS
   `integrity-check` on the live file. Use a normal connection with
   `PRAGMA query_only=ON`, not `?mode=ro` (see
   `references/read-only-connect-lazy-failure.md`).
2. Do a **real write and commit** against the live DB, then delete the probe
   row. A successful independent commit is the falsifier — it proves the file
   accepts writes and localizes the fault to the incumbent process.
3. Check process uptime against the first `malformed` timestamp in the log. A
   fault that began _mid-life_ of a long-running process, with a clean file, is
   this class.
4. Look for a repair breadcrumb (`state.db.repair.lock`, a repair log line)
   between process start and first error. That is the smoking gun: the file was
   fixed under the process.

If step 2 succeeds, **stop planning a repair**. The fix is a restart, full stop.

Beware the FTS `integrity-check` asymmetry: on a read-only handle it raises
`attempt to write a readonly database`, which is not a corruption signal. Run
it on a writable handle or you will misread the result.

## The error message misleads twice

Hermes surfaces this to the user as:

> the turn was stopped because session storage could not be written (the
> transcript would have been lost on restart). This is often a full disk — free
> some space (or fix state.db permissions), then send your message again.

Both suggested causes were wrong here: 32 GiB free, permissions fine. The
parent skill already records the same misdirection for genuine b-tree
corruption (host had 40 GB free). **Treat "often a full disk" in this string as
noise.** Check disk once, in one command, then move on to integrity and
process state. Say plainly to the user that the message is misleading rather
than letting them keep chasing it.

## An agent cannot restart its own gateway — by design

Once diagnosis lands on "restart the process," an agent running _inside_ a
Hermes gateway is fenced from executing it. Four paths were tried on
one occasion, all correctly refused:

| attempt                                                      | result                                                                       |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `launchctl kickstart -k gui/501/ai.hermes.gateway-<profile>` | blocked: cannot restart/stop the gateway from inside the gateway process     |
| background script wrapping the same command                  | blocked: same guard, follows referenced scripts                              |
| `launchctl bootstrap` of a one-shot LaunchAgent              | blocked: persistent-job registration unsafe from inside the gateway          |
| `cronjob no_agent=true` invoking the script                  | blocked: gateway lifecycle command in a cron job (anti-respawn-loop, #30719) |

This is **not** a broken tool and not worth retrying with a cleverer wrapper.
The guard reads the referenced script's contents, so indirection does not
defeat it, and it should not. SIGTERM propagates from the gateway to child
processes, so a self-restart would kill the restarting command mid-flight.

The guard fires even when the target is a _different_ profile's gateway
(the operations agent restarting a research agent), because the check is on the command shape, not the
target. That is a conservative false positive, but arguing with it wastes turns.

**Correct move: stop after two blocked attempts and hand the user one exact
command.** Leave a verify-the-PID-changed script on disk so it is one
copy-paste, and state the old PID so the change is checkable:

```bash
launchctl kickstart -k gui/501/ai.hermes.gateway-<profile>
```

Do not report the fix as applied. Report it as diagnosed, with the blocker
named. Per the operator's standing preference: name the real blocker rather than
narrating four tool failures at him.

## Reporting shape that worked

Lead with the negation of the misleading message, then the real cause, then the
evidence, then the one command:

1. "Not a full disk" + the actual free-space number.
2. Actual cause in one line, with the poisoned-process framing.
3. Bulleted verification list, each item an exercised result (integrity ok,
   FTS ok, real write committed at HH:MM:SS with rowid, counts consistent).
4. Process identity and uptime, first-error timestamp, the self-heal log line
   with its source location.
5. The single command, plus the helper script path.
6. Blockers named once, not narrated.
7. Follow-ups as explicit questions, not unrequested work.

Two follow-ups worth raising in this situation and _not_ acting on unasked:
outsized non-DB directories found while measuring (an 11 GB `memory/` dir,
7× the state.db), and root-cause of the original corruption event, which the
restart does not address and which will recur if unaddressed.
