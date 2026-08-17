# Runner lessons — 2026-07-19

Session context: nightly PR review sweep across `example-org` and `TechNickAI`,
lookback 7 days, max 10 PRs, excluding `TechNickAI/openclaw-config`. Scanned 34 merged
PRs, found 2 flagged, dispatched 2 to Claude Code (hand-dispatched — under the 5-PR
dispatcher threshold), opened 2 follow-up PRs. Both PRs verified at zero residual
unhandled comments. Total wall-clock ~15 minutes including both dispatches.

## Durable lessons

### "Deliberate regression guard" is a distinct decline subtype

The skill already names "declined as deliberate design choice" as a third outcome category
(see 2026-07-16 reference). This session surfaced a stronger, more specific subtype:
**deliberate regression guards** — tight assertions, hardcoded-value checks, or
string-substring guards that exist explicitly to prevent a specific past incident from
recurring. The distinguishing signal is an **inline comment referencing the incident**,
not just a general "keep for clarity" note.

Real example (sample-dashboard #16): gemini flagged two string assertions in
`tests/test_capture_sidecar.py` as "fragile":

```python
assert "subaccount=3" not in src, "subaccount must not be hardcoded to 3 (or any number)"
assert "subaccount=crawdad_sub" in src, "tape client must use env-resolved subaccount"
```

But line 167 of the same file documents the incident:

```python
# The subaccount must be read from env, NEVER hardcoded — hardcoding the wrong number
# silently showed 21 stale fills and missed 1300+ real trades (2026-07-18 incident).
```

The sub-agent correctly declined both as WONTFIX with a thumbs-down, citing the incident
comment as evidence the assertions are intentional guardrails. Python kwarg convention
(`subaccount=3`) means the exact string is the form any regression would take — a regex
adds complexity without meaningful protection.

**Recognition signal for future runs:** when a bot flags an assertion or guard as
"fragile" or "too tight," check the surrounding lines for an incident comment (dates,
fill counts, "silently showed," "missed," "caused"). If present, the guard is a
regression guard — decline with a reply referencing the incident, not a fix. This applies
to: string assertions against hardcoded values, type checks that seem overly strict,
defensive `assert` statements, and "redundant" validation checks.

### Exit-immediately prompt pattern is now the stable default

Both dispatches this session used the prompt line:

> "Once the fix PR is created (or all comments are triaged as declined/self-healed with
> replies+reactions posted) and the original comments are addressed, EXIT IMMEDIATELY.
> Do not idle polling CI checks on the follow-up PR."

Combined with `--dangerously-skip-permissions`, both runs self-terminated cleanly:

- market-service #800 (10 comments): ~9 min, 6 fixes + 8 declines, 16/16 tests pass
- sample-dashboard #16 (3 comments): ~3 min, 1 fix + 2 declines

Zero manual kills, zero CI-polling tails, zero `process(action=kill)` interventions.
This is now confirmed across 12+ PRs total (10 from 2026-07-11 + 2 here). The
exit-immediately line should be treated as a mandatory part of every dispatch prompt,
not an optional optimization.

### Orchestrator triage guidance in the dispatch prompt helps

Passing the orchestrator's Contents-API findings into the dispatch prompt (as
"Triage guidance from the orchestrator's review") helped the sub-agent reach correct
decisions faster. For sample-dashboard #16, the prompt noted the incident comment at
line 167 and suggested "declined as deliberate design choice" as a valid outcome —
the sub-agent adopted this reasoning directly. This is a lightweight way to steer the
sub-agent without overriding its autonomy on the actual code changes.

### Clean 2-PR run confirms hand-dispatch threshold

2 flagged PRs, 2 dispatched, both resolved. Confirms the <=4 hand-dispatch threshold
is correct. The serial dispatcher script's setup overhead (scan JSON format, env knobs,
results file) would have added friction without benefit at this scale.

## Session-specific artifacts created

- `example-org/market-service#801` — follow-up PR for backtest smoke-test fixture bugs
  (tick rate unit, auto_now_add bypass, tick range, dead re-export, docstring).
- `example-org/sample-dashboard#17` — follow-up PR for empty-string env guard.

Do not hard-code these artifact numbers into future sweeps; they are examples of the
report content, not reusable targets.
