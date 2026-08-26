# Severity From The Wrong Source

A distinct noise class from prompt floods and display bubbles. Here the message
volume may be _correct_ — one message per event — but every message is rendered
at the wrong severity, or a dedup you actually built never suppressed anything.

The owner's complaint sounds like noise. The defect is in **where severity comes
from** and **whether the counter is wired to the gate**.

Trigger phrases: "cron failed" on a job that worked · "everything is critical" ·
"the red stop sign stopped meaning anything" · "I built dedup and the flood
continued" · a wrapper reporting a failure whose payload is a real business
event.

---

## 1. Severity belongs to the RUN, not the JOB

The tempting design is one flag per job (`critical = true`) that decides how its
failures render. It is wrong, and it fails in the direction that destroys trust:
every hiccup from an important job renders at maximum severity, so the operator
learns to ignore the loudest signal you have.

Measured on a real fleet: a flag-driven wrapper emitted "🛑 CRITICAL — this job
moves real money" for a 120-second network timeout and for a guard that had
genuinely stopped guarding, at identical volume. One of those needs waking
someone up. The other does not.

**The rule.** A job-level flag may raise the **CEILING** a run is allowed to
reach. It must never set the **FLOOR** every event renders at. Severity is
computed per run from what actually happened.

### Reaching the top severity needs more than a flag

Do not let "critical" be a single adjective any caller can assert. Require a
conjunction that is mechanically checkable:

1. Real money / real harm is at risk **right now**.
2. An unattended exposure exists (an open position, an in-flight transaction).
3. The automated protection itself has stopped working.
4. Only the owner can fix it.

A guard job whose desk is in paper/sandbox mode fails condition 1 and cannot be
critical no matter what its spec says.

### Clamp loudly, never silently

When a run asks for a severity it has not earned, **downgrade it and say why**:

```
⚠️ DEGRADED — <job> (exited 30)
NOTE: emitted critical but was clamped. SPEC BUG: CRITICAL requires money=live,
this job is 'none'. Condition 1 of the four-condition test fails.
```

A silent downgrade is indistinguishable from the classifier being broken. The
clamp notice is what lets someone fix the spec.

### Prove the label is still EARNABLE

Clamping without a positive control is censorship, not calibration. Ship two
tests side by side:

- a job that asks for critical without the qualifying context → **clamped**, and
  the card says so;
- a job that genuinely has the qualifying context → **reaches critical**.

If only the first exists, you have proven you can suppress the label, not that
it still works.

---

## 2. Derive risk context from behavior, not declaration

A spec that _says_ it is paper/sandbox while its script points at a production
endpoint is the dangerous direction: the alarm is quieter than reality.

Use **declared + independently detected**, and treat disagreement as a
configuration error:

- over-declaring risk (says live, looks harmless) — **allowed**, louder than
  warranted is safe;
- under-declaring risk (says paper, looks live) — **hard refusal**, do not run.

Three implementation traps, all found in one session:

- **Check it BEFORE launch, not on the failure path.** A mismatch discovered
  while rendering a failure card means the job already ran. Worse, a mismatched
  script that _succeeds_ is never examined at all. Reconcile in preflight.
- **Scan the file that actually executes.** If execution resolves
  `HOME/scripts/<name>` but the scanner reads `<cwd>/scripts/<name>`, a
  same-named decoy silently classifies a live job as harmless. Share one
  resolver between the scanner and the launcher.
- **Follow one hop of wrapper indirection.** The markers frequently live in the
  `.py` a `.sh` invokes. Scanning only the named file misses them. Bound the
  depth so this cannot recurse forever.

---

## 3. Counting is not suppressing

This is the one that ships, passes review, and is praised — because the card
_says_ "Occurrence 28", which reads like dedup is working.

The defect: the code increments an occurrence counter, then unconditionally
renders and delivers on every tick. N repeats still produce N notifications, now
helpfully labelled. **The feature's headline claim was false in production while
its own status output looked correct.**

Wire the counter to a delivery gate. Speak when:

- it is the **first** occurrence of the condition;
- an **escalation milestone** is crossed (age-based, so an unacknowledged alarm
  gets louder rather than repeating at full volume);
- a **state change** happens (job stopped, real repair attempted);
- the run is genuinely top-severity — a live-money guard must never be
  summarized into silence, because a missed page there is unrecoverable in a way
  a duplicate page is not.

Everything else records to the ledger and prints one line locally:

```
(suppressed: duplicate of an open condition (occurrence 7))
```

Silent must not mean invisible to whoever reads logs by hand.

### Two follow-on bugs in the same gate

- **Shadow/dry-run rehearsals must not count as "state changed".** If the
  dispatch flag is true in rehearsal mode, occurrence 2 of _every_ condition
  emits a second card and most of the flood returns. Carry an explicit
  `shadow` flag and gate on it.
- **A success must reset the streak — for every row, not just open ones.** An
  early version reset only rows not already marked resolved, so a job
  alternating fail/success kept its streak across cycles and still tripped a
  "two consecutive failures" gate. Zero the counter on **every** success; only
  the phase transition is conditional.

**Verify by alternation, not repetition.** Repeated identical failures are the
easy case. The tests that find real bugs are fail → success → fail, and
rehearsal-vs-real.

---

## 4. The child's exit contract is not yours

Scripts in the wild encode domain meaning in exit codes, and the conventions
conflict. Real examples from one profile:

| script             | 0             | 1                                 | 2               | 4                                  |
| ------------------ | ------------- | --------------------------------- | --------------- | ---------------------------------- |
| desk monitor       | healthy       | **tripwire fired — look at this** | watchdog broken | —                                  |
| position guard     | ran correctly | —                                 | guard broken    | —                                  |
| research collector | —             | —                                 | —               | a research **state**, not an error |

A wrapper that treats every non-zero as failure converts "tranche 2 filled,
place your stop" into "⚠️ exited 1", which the scheduler then wraps again into
"Cron failed: script exited with code 3". Three layers deep, the actual business
event is truncated at the end of a message that looks like garbage.

**The signal was the payload and the wrapper made it look like a defect.**

Design rules:

- Keep **child** and **runner** exit namespaces separate. The child's code
  describes a domain outcome; the runner's own codes describe execution state.
- Offer an explicit outcome band scripts can migrate onto (e.g. healthy /
  noteworthy / degraded / broken) that avoids reserved ranges — 1, 2, sysexits
  64–78, 126/127, 128+N signals.
- Treat unrecognized non-zero as a **hard failure**, never silently downgraded.
  Backwards compatibility must not become a quiet reclassification.
- Prefer an optional structured result line for richer meaning, with strict
  precedence: runner-observed termination overrides the child's claim, the exit
  code sets a floor, the structured line may **raise** severity but never lower
  it, and malformed metadata never turns failure into success.
- **Before migrating a script, read its exit convention** — it is very often
  written in a comment at the top of the file. Do not infer it.

### Sanitize free text from the child

Any summary the child provides flows into a card that is printed **and** sent to
a chat. If redaction only covers raw stdout/stderr, a token placed in a
structured summary bypasses it entirely. Run every child-provided free-text
field through the same redactor and bound its length — including non-numeric
values inside a metrics map.

---

## 5. Never claim an action you did not perform

A quarantine/pause/disable path that flips a database row and returns "job
paused" — without calling the scheduler — leaves the job running at full cadence
while its incident is marked handled. The operator is told something stopped
while it keeps going. That is strictly worse than either honest outcome.

- Perform the real action first; mark state **only after it succeeds**.
- On failure, say so explicitly (`STILL RUNNING`, plus the manual command) and
  leave the incident open.
- Never auto-disable a money/safety/backup/monitoring job. Prefer **fail-visible
  quarantine**: the hazardous work stops, but the incident, heartbeat, and a
  recurring dead-man reminder stay alive. A job that is off must prove it is off.

Test the failure path explicitly, with the real action stubbed to fail. In a
sandbox without a scheduler this is also why direct-call tests need the stub:
the honest implementation now _correctly_ refuses.

---

## 6. Verification specific to this class

- [ ] Severity computed per RUN; the job flag only raises a ceiling.
- [ ] Top severity requires the multi-condition test, not a single adjective.
- [ ] Clamps are announced as spec bugs, never silent.
- [ ] A positive control proves top severity is still **reachable**.
- [ ] Risk context = declared **and** detected; under-declaration refuses to run.
- [ ] Reconciliation happens in preflight, before the child executes.
- [ ] Scanner and launcher resolve the same path; one hop of indirection followed.
- [ ] The occurrence counter is wired to a delivery **gate**, proven by counting
      actual deliveries — not by reading "Occurrence N" on a card.
- [ ] Rehearsal/shadow runs do not speak.
- [ ] Alternating fail/success resets the streak and dispatches nothing.
- [ ] Child exit conventions read from the script before migrating it.
- [ ] Unrecognized non-zero stays a hard failure.
- [ ] Child-provided free text is redacted and length-bounded end to end.
- [ ] Any "paused/disabled/stopped" claim is preceded by the real action
      succeeding; the failure path is tested.
- [ ] Validated against **every real spec on a profile**, not only fixtures
      (see §7).

---

## 7. Fixtures cannot find configuration-shaped bugs

Two defects in this session survived a large green fixture suite and were found
only by running the loader across every real spec on a live profile:

- A bare job id resolved against the current directory first, so a **state
  directory named exactly like the job id** shadowed the real spec. Two live
  jobs failed with "Is a directory" and had silently never run.
- Specs whose declared risk class disagreed with their script's behavior.

Write a spec-validator that loads and preflights every spec through the runner's
**own** parser — the same code path the scheduler uses — and prints a table of
declared vs detected attributes. Run it on every profile before and after any
migration.

Do **not** use a dry-run flag as the validator if dry-run still executes the
script; validate by loading and preflighting instead.

Related: the monitor-side view of the same problem, and
`llm-triage-not-regex-severity.md` in this directory for deciding severity of
_prose_ (a judgement) versus of _structured run outcomes_ (this file).
