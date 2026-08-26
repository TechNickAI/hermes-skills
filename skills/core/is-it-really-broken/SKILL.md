---
name: is-it-really-broken
description: >
  Use when a health check, audit, or monitor says something is BROKEN, before
  repeating that to anyone. Re-runs the check from the same context the failure
  came from and separates real failure from unknown, since a timeout, an HTTP 000,
  or a permission error means the test could not answer — not that the thing is
  down. Prevents reporting an outage that is actually a broken probe.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [monitoring, diagnostics, integrations, reliability, reporting]
    related_skills: [robustify-doctor]
---

# Integration Health Triage

## Overview

An integration audit's `BROKEN` verdict is a **test result, not a fact**. Audits
probe one way; the runtime often reads another. Relay verdicts verbatim and you
send people chasing phantoms — which is how a monitoring system permanently
loses its reader's trust.

This skill governs the gap between "the audit said X" and "here is what actually
needs your attention."

Measured rate on a real run (one occasion, a fleet member's weekly Integration
Health Check): 7 items came back BROKEN/PARTIAL, and **3 of the 7 were audit
bugs, not outages.** Assume roughly a third of any verdict list is wrong until
verified.

## When to Use

- A live integration audit produced a verdict file (`verdicts.json`, `REPORT.md`)
  or a weekly "Integration Health Check" cron delivered findings
- An owner reports "my automations aren't working" against a green status list
- Someone asks "what else is broken?" / "what needs my attention?"
- A cron job touching third-party services failed, hung, or went quiet
- An owner reports their agent keeps mentioning "still open" items, off-topic or
  in the middle of unrelated work — see
  `references/stale-agent-open-items.md`

Deep-dive reference: `references/stale-agent-open-items.md` — verifying an
agent's self-reported open items against live state (plugin mtime vs. gateway
start time, per-interpreter Full Disk Access, the two distinct macOS iMessage
faults), and how to rewrite the stale memory entry that caused the nagging.

Zero-output reference: `references/zero-byte-subprocess-forensics.md` — when a
subprocess or model seat reports 0 stdout and 0 stderr, classify invocation
rejection vs. timed-out agent loop vs. router failure vs. alias fallback using
child exit status, session DB state, and actual router attribution. Includes the
background-shell trap where a final `wc` makes a failed panel script exit 0.

Do not use for: diagnosing one known-broken job (read its log), or general host
health (that is `robustify-doctor`).

False-negative reference: `references/silent-extraction-failure-as-false-negative.md`
— the inverse failure mode, where a broken decoder/parser returns empty-looking
output and the agent reports it as a fact about the world ("you have no messages
about X" against 1,946 real messages). Covers the mandatory coverage-rate gate,
smell tests, the verified `attributedBody` decoder, and how to tell the user.

Zero-result reference: `references/silent-zero-result-query-traps.md` — the sibling
case where the decoder works but the _filter_ excludes every row (SQLite type
affinity comparing an INTEGER expression against `strftime('%s',...)` TEXT matches
nothing, silently). Covers the mandatory scan-count print, the control-query triple
that localizes a bad predicate in one call, why masked/redacted CLI output cannot be
used as a lookup key, and the rule for reporting a one-sided record as a visibility
boundary rather than a non-event.

False-GREEN reference: `references/false-green-from-incomplete-enumeration.md` —
read before repeating any SUCCESS verdict. Covers the class where a check passes
because it enumerated a hardcoded list written when the system was smaller: a
self-test that isolated every state dir except the one added later, a sync that
mirrored one file after the code grew to three (merge reported success while the
merged feature sat inert through 420 clean runs), and a monitor summarizing its
own subset. Includes why `try/except ImportError` and `if absent: continue`
convert defects into permanent silence, and the "did it run the way the merge
intended?" probe.

## Step 0 — Never let a failed read become a factual negative

Triage runs both directions. An audit calling something BROKEN when it works is one
error class; a broken read path reporting "nothing found" as truth is the other, and
it is the more damaging one — it costs the user's trust rather than your time.

Before any "I found no X" that rests on parsing, decoding, or transforming data:

1. Count records you attempted to read and how many yielded usable content.
2. Compute the rate. Set the floor **before** looking at it (95% is a sane default).
3. Below the floor, report the **tool** as broken in plain language and stop. Do not
   report a finding.

Absence of decoded content is **not** absence of data. Suspicious uniformity (every
record empty, every value the same character, framing bytes like `+` / `NSString` /
`\ufffd` showing up in your "text") means you are reading structure, not content. A
zero-result that contradicts what the user remembers is a measurement bug until
proven otherwise.

## Step 1 — Verify every verdict before it reaches a human

For each `BROKEN` / `PARTIAL`:

1. **Find the runtime path, not the audit path.** Where does the _agent_ read
   this credential — `.env`, keychain, `config.yaml`, a plugin DB? Probe that.
2. **Retry every `TIMEOUT` / `rc=-1`.** One timed-out probe is not evidence.
3. **For credentials, check BOTH stores** before believing "not found":
   ```bash
   grep -c 'THE_KEY' "$HERMES_HOME/.env"
   security find-generic-password -a THE_KEY -w | wc -c # macOS
   ```
4. **For CLI-based probes, confirm the CLI and the agent share a config.**
   They frequently do not — see Trap 1.
5. **Classify survivors** into (a) real outage, (b) expired session, (c) audit
   bug. Only (a) and (b) are findings.

## Trap 1 — A CLI's health is not the subsystem's health

Whenever an audit shells out to a CLI, verify that CLI reads the same config the
agent does. Worked example: `cortex status` reads `~/.config/cortex/config`
(`CORTEX_STORE_PATH=`), while the Hermes cortex plugin reads `store_path:` from
`config.yaml` and indexes into `<store>/.plugin.db`. Independent pointers.

A stale CLI path — e.g. a leftover `~/.openclaw/memory` from a prior platform —
makes the CLI fail loudly while agent recall is perfectly healthy. The audit runs
the CLI, reports BROKEN, and everyone panics about memory that was never lost.

Verify agent-side memory directly instead:

```bash
python3 -c "
import sqlite3
c=sqlite3.connect('<store>/.plugin.db')
print('pages', c.execute('select count(*) from pages').fetchone()[0])
print('fts', c.execute('select count(*) from pages_fts where pages_fts match ?',('listing',)).fetchone()[0])
print(c.execute('select rel_path from pages order by rowid desc limit 3').fetchall())
"
```

Non-zero pages + recent `rel_path` entries + non-zero FTS hits = healthy,
whatever the CLI says.

**Before repointing any stale config, prove which store is live.** Compare page
counts AND newest-file mtimes across every candidate. In the run above, the
config backup pointed at a cloud-drive store with 11 pages last touched three
months prior, versus 448 local pages written that day — "restoring" the backup
would have swapped a live store for a dead one. Afterward the CLI may create its
own empty sidecar DB and report `no such table: sources`; cosmetic, not evidence
of empty memory.

## Trap 2 — The delivered alert text lies about the cause

A job alerted as _"provider timeout. Fallback chain was exhausted or
unavailable."_ The actual recorded error:

```
TimeoutError: Cron job '...' idle for 603s (limit 600s)
  — last activity: executing tool: terminal
  iteration=45/500
```

Nothing to do with the provider; the fallback chain was never involved. The job
hit a credential wall, improvised a browser workaround, and hung on a `terminal`
call until the **inactivity watchdog** killed it.

Always read the job's own `last_error` and the run output's `## Error` block
rather than the delivered alert string. Generic catch-all alert text actively
misdirects and costs several probes before the mismatch shows.

## Trap 3 — A hung job is indistinguishable from a healthy silent one

Jobs emitting `[SILENT]` or `HEARTBEAT_OK` when clean look exactly like jobs that
died silently — from the owner's chair, both produce nothing. An owner insisting
"nothing works" against a green list is usually reporting this, and they are
right: **absence of output is not evidence of success.**

When you find it, that structural insight _is_ the finding. Fixes that help:

- Make credential/login helpers **fail fast and loud** instead of proceeding with
  an empty value. A helper returning `""` on a locked keychain let an agent burn
  45 iterations chasing a phantom; one printing `BROKEN: keychain-locked` and
  exiting non-zero turned a 10-minute hang into a 1-second actionable result.
- Add explicit **per-step time limits** to any prompt driving browser/login work:
  `timeout 90 <cmd>`, a stated per-integration ceiling, and a hard rule that a
  partial report must still be delivered. Silence is a failure mode.
- Instruct the job that on `BROKEN:` / `MISSING_CREDS` it must **record and move
  on** — not search elsewhere, not improvise, not retry.

## Trap 4 — An agent's own "still open" list is unverified state

An agent's `MEMORY.md` to-do has no expiry and no verification step. Items get
resolved by unrelated work (a gateway restart for another reason, an OS service
recovering) and the note is never cleared, so the agent keeps reporting them —
often bolted onto unrelated conversations, which reads to the owner as the agent
malfunctioning.

Verify before relaying, and verify before accepting the "it's glitching" frame.
Measured on one run: an agent reported two open items to its owner mid-task and
**both were already resolved**. Decisive checks:

- _"Plugin X needs a restart to activate"_ → compare plugin file mtime against
  the running gateway's start time, then confirm with
  `hermes_cli.main plugins list`. Many gates log **nothing** on successful
  registration, so a zero grep count in `gateway.log` is not evidence of absence.
- _"chat.db / FDA is broken"_ → resolve the live interpreter with
  `lsof -p <pid> | awk '/txt/ && /python/'` and read `chat.db` as that exact
  binary. Old denied rows in `TCC.db` for retired interpreters are expected and
  are not evidence about the current one.

Then fix the memory entry, not just the fault — clearing the fault without
clearing the note guarantees the nagging resumes next session. Full procedure in
`references/stale-agent-open-items.md`.

## Trap 5 — A responsive surface is not a healthy subsystem

The inverse of Trap 3. There, silence hid failure; here, a perfectly chatty
service hid a fully broken persistence layer.

Measured on one run: a trading agent answered Telegram normally while **every**
database operation had been failing for ~20 hours. The messaging path does not
touch the session store, so any check that pings the chat surface — or asks the
agent "are you OK?" — returns GREEN over a dead subsystem. Silently failing the
whole time: transcript appends, session creation, routing saves, token
accounting, and context compression (so long sessions could not compact and just
degraded).

The generalization: **probe the subsystem you are making a claim about.** An
agent replying to you proves the inbound/outbound message path works and nothing
else. Ask what a component's failure would actually look like from where you are
standing, and if the answer is "identical to healthy," you need a different
probe.

Cheap probes that would have caught it:

```bash
# does the error appear in the service's own log?
journalctl --user -u <unit> --since "1 hour ago" | grep -ci "not a database\|I/O error"

# does a write actually land? (read back what you wrote)
# does the row count move between two samples taken minutes apart?
```

Two corollaries worth carrying:

- **Grep the literal error string to measure the fix**, not just to find it. The
  same `grep -c` that proved the fault becomes the post-fix acceptance test
  (`want 0`).
- **An escalating error string marks the timeline.** The fault opened as
  `disk I/O error` and degraded to `file is not a database` about two hours
  later. Grepping for the _first_ occurrence of each variant dated the incident
  precisely without any monitoring history.

## Step 2 — Report in the shape the owner can act on

Separate the classes and name the shared root cause. The pattern is the real
answer, not the list:

1. **Real, needs a human** — say exactly who must act (owner at the machine vs.
   you) and what the one action is.
2. **Expired sessions** — repeated logouts are session hygiene, not integration
   failure. Do not inflate them. An owner reframed this himself: _"Stuff keeps
   getting logged out. That is annoying, but not really an integration failure."_
3. **Audit bugs** — say the audit was wrong, and fix the probe.

In the worked example, one locked login keychain accounted for two real
breakages plus one false alarm, and the same class of OS permission gap accounted
for a fourth. Two root causes wearing five masks. Leading with that beats leading
with a seven-item list.

## Step 3 — When the owner says "just fix it"

Verbatim owner correction mid-session: _"Just fix it. There are too many problems
for me to read through walls of text and decide the solution to all of them for
you."_

This fired after a technically-correct writeup: a timeline table, a two-bug
analysis, and a closing menu of four proposed fixes. Every fact was right and the
message still failed — it handed a non-technical owner a reading assignment plus
a decision she had no basis to make.

Once overload is signalled, or any version of "just fix it" is said:

- **Drop the diagnosis narrative entirely.** No timelines, no log excerpts, no
  "here's what I suspected then ruled out." That is your working process, not the
  deliverable.
- **Do the work, then report three things:** what was wrong (one or two plain
  sentences), what you fixed (past tense, verified), what still needs a human and
  precisely who must do it.
- **Never close with a menu.** Pick the sound option, execute, say you did.
- **Keep the honest limit, lose the hedging.** "This one needs a click on the
  Mini" is respectful; three paragraphs on the macOS permission model is not.
- **Verify before claiming.** "Tested it — now fails in 1 second instead of
  hanging for 10 minutes" beats "should be fixed." An owner burned by false
  "passed" reports needs the receipt, and one line carries it.

Litmus test: _if the owner read only the first two sentences, would they know
whether their problem is gone?_

## Step 4 — When an owner contradicts your status report, they are right

Verbatim, after a green "all passed" summary: _"Truth about what is actually
working: spam check - fail; contact steward - fail; lead intake - fail... Get it
together dogs!!"_

Lived experience outranks any self-reported job status. `[SILENT]`,
`HEARTBEAT_OK`, and `last_status: ok` prove the agent loop finished — not that
work reached the human.

- **Concede immediately, without defensiveness.** "If the jobs aren't producing
  real output for you, they failed." Do not re-litigate passing test results.
- **Then get ground truth from the box** — read actual run-output files, not the
  prior session's summary about them.
- **Treat "it always seems to be X" as a hypothesis worth testing**, not a
  complaint to soothe. An owner's _"every time I look it's always iMessage"_ was
  correct in spirit and led straight to the shared root cause.

## Pitfalls

1. **Backing up before editing another person's machine is not optional.** Copy
   any config/script/jobs file before patching, with a dated suffix, and say so
   in the report — an owner who has been burned needs to hear "reversible."
2. **Do not kill processes that look stale but are load-bearing.** Long-running
   browser helper processes belonging to a healthy daemon are normal; check the
   daemon's health endpoint before reaping anything.
3. **Editing tools that operate on the local filesystem do not reach a remote
   host.** Write the patch script locally, copy it over, run it there, then
   verify with a syntax check on the remote.
4. **A verdict of REMOVED/absent is usually intentional.** Confirm before
   "restoring" an integration someone deliberately dropped.

## Verification Checklist

- [ ] Every BROKEN verdict re-probed against the runtime path, not the audit path
- [ ] Any "found nothing" claim backed by a measured extraction coverage rate, with the
      denominator (population searched) printed
- [ ] Empty-looking decoded output inspected for framing bytes before being called empty
- [ ] Every `TIMEOUT` / `rc=-1` retried at least once
- [ ] Credentials checked in BOTH `.env` and keychain before "not found"
- [ ] Any CLI-based verdict cross-checked against the agent's own config/DB
- [ ] Live store confirmed by page count + mtime before repointing any config
- [ ] Job's own `last_error` read, not just the delivered alert text
- [ ] Findings split into real / session-hygiene / audit-bug, with shared root
      cause named
- [ ] Any agent-reported "still open" item verified against live state before relaying
- [ ] Stale memory entries rewritten (backed up first) so the item stops recurring
- [ ] Backups taken and mentioned for every file edited on someone else's machine
- [ ] Any "it's responding, so it's fine" claim replaced by a probe of the
      specific subsystem being vouched for
- [ ] Fixes verified by re-running, not inferred from exit code
