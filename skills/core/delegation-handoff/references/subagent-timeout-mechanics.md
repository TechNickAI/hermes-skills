# Subagent timeout mechanics (H‍ermes)

Read this before diagnosing "the subagent timed out" or before promising a caller that a
long-running delegated task can be given more time. Verified by code read of
`~/.h‍ermes/h‍ermes-agent/tools/delegate_tool.py` on 2026-08-15.

## There is no per-call timeout parameter

`DELEGATE_TASK_SCHEMA` (~line 4497) exposes `goal`, `context`, `tasks`, `role`,
`output_schema`, and the control actions. **No timeout field, top-level or per-task.** A
skill, prompt, or caller therefore CANNOT scale a subagent's budget to the size of the job.
Do not write guidance that assumes it can, and do not tell a user "I'll give this one a
longer timeout" for a `delegate_task` dispatch.

The only levers are process-wide and read at call time (`_get_child_timeout`, ~line 819):

- `delegation.child_timeout_seconds` in `config.yaml`
- `DELEGATION_CHILD_TIMEOUT_SECONDS` env var (fallback)

Semantics: `0` or negative = **disabled**, positive = hard cap with a floor of 30s.

## Upstream default is NO cap — a nonzero value is a local override

`DEFAULT_CHILD_TIMEOUT: Optional[float] = None` (~line 998). The docstring is explicit that
the old blanket cap was removed because deep code review, large research fan-outs, and slow
reasoning models were being killed mid-task while making steady progress.

So when a child dies at a suspiciously round number, **check whether a profile set the key**
rather than assuming a framework limit:

```bash
for f in ~/.h‍ermes/config.yaml ~/.h‍ermes/profiles/*/config.yaml; do
  echo "$f -> $(grep -n 'child_timeout_seconds' "$f" || echo '<unset>')"
done
```

## Three different clocks, three different failures

Diagnose by which one matches the elapsed time, not by the word "timeout" in the message.

| Clock                              | Where                                                                                                   | Fires when                                                                                                                                                                                                    |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `delegation.child_timeout_seconds` | `_get_child_timeout`, result(timeout=…) at ~2585                                                        | Hard wall-clock kill of the child. Result carries `status: timeout`, `timeout_phase`, `timed_out_after_seconds`.                                                                                              |
| Heartbeat staleness monitor        | `_HEARTBEAT_STALE_CYCLES_IDLE`=15×30s=450s; `_HEARTBEAT_STALE_CYCLES_IN_TOOL`=40×30s=1200s (~line 1014) | Child shows no progress. Parent stops heartbeating so the **gateway** inactivity timeout (`agent.gateway_timeout`) fires. Runs even with the hard cap disabled — this is the intended stuck-child protection. |
| `terminal.timeout`                 | profile `config.yaml`                                                                                   | Any reviewer/worker launched as a headless one-shot (`h‍ermes -z …`) through the terminal tool. Commonly 180s, far below what deep-panel guidance assumes.                                                    |

An in-flight model wait is **not** idle: `direct_api_call` refreshes `last_activity_ts`, so
slow reasoning models are not killed by the idle window. A child stuck inside one long tool
call is what the 1200s in-tool ceiling targets.

## Diagnostic artifact

On a timeout with **zero API calls**, the tool writes
`logs/subagent-timeout-<id>-<ts>.log` (`_dump_subagent_timeout_diagnostic`, ~line 1896) with
the config'd timeout, tracker snapshot, and every thread's stack. Zero-API-call timeouts mean
the child never reached its first LLM request — a startup problem, not a slow model.

## Removing a local cap (measured 2026-08-15)

Restoring the upstream default is a one-line edit per profile, but do it with the
fleet-uniformity discipline: the key can appear in the root config AND every named
profile, and each occurrence is the sole line under its own `delegation:` block.

```bash
# 1. Inventory FIRST — never assume only your profile set it
for f in ~/.hermes/config.yaml ~/.hermes/profiles/*/config.yaml; do
  echo "$f -> $(grep -n 'child_timeout_seconds' "$f" || echo '<unset>')"
done
# 2. Back up, then edit BY ASSERTED LINE NUMBER (a key can recur under
#    different parent blocks; never blind string-replace)
# 3. Prove the parse and the resolved value, per profile:
HERMES_HOME=~/.hermes/profiles/<p> venv/bin/python -c \
  "import sys; sys.path.insert(0,'.'); from tools.delegate_tool import _get_child_timeout; print(_get_child_timeout())"
# want: None
```

Three verification points that are easy to skip and worth the calls:

1. **`_get_child_timeout()` returning `None`** is the real proof, not the YAML value —
   it exercises the same parse path the tool uses (`0` or negative ⇒ disabled).
2. **Check the env fallback isn't shadowing it.** `DELEGATION_CHILD_TIMEOUT_SECONDS` in
   any `.env` overrides an unset config value; grep for it before declaring the cap gone.
3. **No gateway restart is needed.** `load_config_readonly` caches on the config file's
   `(st_mtime_ns, st_size)` (`hermes_cli/config.py`, `_load_config_impl`), so a running
   gateway picks the edit up on its next read. Don't restart the operations agent's own gateway to
   "apply" a config change of this kind.

Tradeoff to state plainly when reporting: with the hard cap gone, a genuinely wedged
child no longer dies at a round number — it stalls until the heartbeat staleness monitor
stops parent heartbeats and the gateway inactivity timeout fires. That is the intended
protection, but if a wedged child ever hangs a panel, the lever is
`_HEARTBEAT_STALE_CYCLES_*`, not restoring the blanket cap.

## Consequences for briefs

1. **Budget is fixed at dispatch time.** If a review or research job might exceed the cap,
   split it or run it as a headless one-shot with an explicit per-call `timeout=` (terminal
   foreground max 600s; use background + poll beyond that).
2. **Make partial work survivable.** A hard kill discards the child's summary. Instruct
   children to append findings to a workspace file incrementally, so a killed run still
   leaves evidence. Real cost of not doing this, 2026-08-15: a review child found a genuine
   bug in the user's code and was killed before writing a summary — the finding was only
   recoverable because the user happened to see it mid-stream.
3. **Do not "fix" a slow reviewer by bypassing the configured router.** Slow is not broken;
   headless one-shots pay session/context startup before the model reasons.
