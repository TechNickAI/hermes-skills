# Zero-byte subprocess and model-seat forensics

Use this when an integration, reviewer, cron step, or headless agent subprocess reports **0 stdout bytes and 0 stderr bytes**.

## Core rule

`stdout=0, stderr=0` proves only that the wrapper captured no bytes. It does not prove the upstream was dead, the model returned an empty opinion, or the process exited successfully.

A headless agent can complete many intermediate model/tool turns without writing stdout because the CLI emits only the final answer. If a deadline kills the agent before that final answer, `timeout` may terminate quietly and leave both output files empty.

## Failure classes

Distinguish these empirically:

1. **Invocation rejected:** no child session; binary/provider/model validation failed. Usually stderr contains the diagnostic.
2. **Timed-out agent loop:** child session exists with intermediate assistant/tool turns and token use but no final answer; router may show successful calls followed by client disconnect near the deadline.
3. **Router/upstream failure:** call logs contain non-2xx status and an error summary in the run window.
4. **Alias fallback/family collapse:** requested alias starts under a fallback model or router telemetry shows a different provider/model than the label promised.
5. **True empty completion:** request finished normally but response-level evidence shows empty content. Shell byte counts alone cannot establish this.

## Evidence order

1. Quote the exact command including timeout, provider/model, redirects, and backgrounding.
2. Record each child PID and child exit code.
3. Inspect stdout/stderr byte counts and contents.
4. Inspect the child session DB: requested/stored model, start/end state, intermediate turns, final assistant message, token use.
5. Inspect router logs for the same timestamp and member key: requested model, combo, actual provider/model, status, error, tokens, correlation ID.
6. Inspect real connection-health fields and alternate provider names before declaring credentials missing.
7. Reproduce a bounded prompt through both the normal shell and the agent terminal environment. A short successful prompt proves reachability only, not that a long agentic job can finish.

## Shell harness trap

This launcher turns child failures into script exit 0:

```bash
timeout 900 command >seat.out 2>seat.err &
# poll output sizes
wc -c seat.out seat.err
```

It backgrounds the child, never captures its status, then exits with `wc`'s code. Use explicit PID tracking and `wait`:

```bash
run_seat() {
  tag=$1; shift
  "$@" >"$tag.out" 2>"$tag.err"
  rc=$?
  printf '%s\n' "$rc" >"$tag.rc"
  if [ "$rc" -ne 0 ] || [ ! -s "$tag.out" ]; then
    printf 'FAILED tag=%s rc=%s stdout=%s stderr=%s\n' \
      "$tag" "$rc" "$(wc -c <"$tag.out")" "$(wc -c <"$tag.err")" >&2
    return 1
  fi
}

run_seat grok timeout 900 hermes -z "$P" ... & p1=$!
run_seat gemini timeout 900 hermes -z "$P" ... & p2=$!
wait "$p1"; s1=$?
wait "$p2"; s2=$?
```

A degraded quorum may proceed, but every failed seat must be machine-visible. Record rc, timeout status, stdout/stderr sizes, and actual served provider/model.

## Attribution rule

A model alias is not evidence of the served family. Fallback can return useful text while defeating panel diversity. Count a seat only when:

- child exit code is 0;
- stdout has a substantive final answer;
- no deadline termination occurred;
- actual served model family matches the promised label;
- output addresses the assigned task rather than setup/tool noise.

## Bounded agent jobs

For self-contained reviews, ask the child to analyze only the enclosed artifact and return the answer directly. Do not assume an empty tool selector actually prevented tools; verify from the child session. Parent-gathered I/O plus bounded child reasoning is more predictable than handing every seat exploratory host access.

## Reporting

Separate:

- completed subprocesses/seats;
- failed subprocesses and failure class;
- requested identity versus actual served identity;
- degraded/quorum decision;
- exact repair.

Never call a zero-byte result an empty opinion. Treat it as an execution failure until response-level evidence proves otherwise.
