# Parallel seat fan-out: a silent kill looks exactly like an empty answer

Applies to any harness that fans work out to N parallel subprocesses and judges
each one by its output file — review panels, model bake-offs, parallel probes,
multi-host collectors. Verified live one occasion.

## The failure

A four-seat review panel reported:

> "Grok and Kimi produced 0 bytes with 0 stderr on both attempts — dead seats.
> Two substantive seats across two model families, so degraded but not
> single-family. Proceeding."

Every part of that conclusion was wrong. Router logs showed both models
answering correctly for the entire run:

```
16:09:18  200  ~x-ai/grok-latest   6,852 tok  121.9s
16:18:08  200  ~x-ai/grok-latest  12,303 tok  207.1s
16:21:49  499  Client disconnected: request_signal_aborted
16:11:06  502  moonshotai/kimi-k3      0 tok  261.7s  (throughput guard)
```

The 499 lands ~900s after launch: the harness's own `timeout 900` killed a
healthy, working reviewer. The agent's session store showed 34 messages and
709k input tokens consumed — it was mid-flight, not idle.

## Why zero bytes on BOTH streams

Four things compose, and each is individually reasonable:

1. `hermes -z` writes only the FINAL answer to stdout. Intermediate tool and
   assistant turns persist to the session DB, never to the pipe. A run killed
   before it concludes emits nothing.
2. GNU `timeout` terminates the child silently. No message, no stderr.
3. The launcher backgrounded each `timeout` with `&`, never `wait`ed a PID, and
   never captured `$?`. The one field that distinguishes "killed" from
   "answered empty" was discarded at the moment it existed.
4. The script ended with `wc -c` and therefore exited 0 regardless.

Net: **a timed-out seat and a seat that returned an empty opinion are byte-for-
byte identical to the consumer**, and the harness reports success either way.

## The deeper defect: an unenforceable rule

The panel skill already carried, in bold, "do not stamp degraded just because a
reviewer is slow — only after a genuine failure or a blown timeout." The agent
did not ignore it. It _could not apply it_, because the mechanism had erased the
evidence the rule depends on.

**Prose instructing an agent to make a distinction its harness destroys is a
rule that cannot be followed.** When you find an agent violating a documented
rule, check whether its tooling still surfaces the input that rule needs before
treating it as a judgment failure.

## Minimum viable harness

```bash
run_seat() {                        # $1 = tag, $2 = model
  timeout "$BUDGET" "$H" -z "$P" --provider "$PROV" -m "$2" \
    --ignore-rules -t '' >"$D/$1.out" 2>"$D/$1.err"
  printf '%s\n' "$?" >"$D/$1.rc"
}

run_seat grok   "$GROK_MODEL"  &  P1=$!
run_seat gemini "$GEM_MODEL"   &  P2=$!
wait $P1; wait $P2                # wait EACH pid individually
```

Classify before synthesis:

| rc  | out       | meaning                    | report as                          |
| --- | --------- | -------------------------- | ---------------------------------- |
| 124 | empty     | killed at the budget       | timed out at Ns — NOT a dead model |
| ≠0  | empty     | failed                     | quote `.err`                       |
| 0   | empty     | genuinely returned nothing | the only real "empty opinion"      |
| 0   | non-empty | success                    | usable seat                        |

**A 0-byte seat is never a valid opinion.** Record it as a failed seat carrying
its exit code, budget, and byte counts, and have the harness surface a
machine-readable degraded status instead of exiting 0.

### The wait-each-PID subtlety

A prior lesson in this same class warns against `wait $PID1 $PID2 $PID3`,
because one stalled worker hangs the whole run while finished results sit unread
on disk. That correctly pushed toward "don't block on everything" — and
overshot into "never wait, never read exit codes," which produced this failure.

Both failure modes are real and the resolution is the same: `wait` each PID
_individually_ and record its rc. A stall then costs one seat rather than the
whole run or the truth about what happened.

## Verify family attribution, not just liveness

A seat can answer healthily while an alias, fallback rung, or provider
substitution routes it to a family already at the table. A `PONG` probe proves
the pipe is open, not who answered.

When the fan-out's entire value is independence (diverse review, cross-model
consensus), confirm the SERVED model from router logs or the response's own
`model` field — not from the alias you requested. Otherwise a nominally
four-family panel silently collapses onto two and still reports full diversity.

## Budget realism

Before blaming a model, compare the per-call latency against the per-seat
budget. Here individual successful calls took 121s and 207s; an agentic reviewer
needing several of those cannot finish inside 900s. The fix is a bigger budget
or a smaller brief, not a routing change and not a new credential.

Related: `references/subagent-timeout-mechanics.md` for the several distinct
clocks that can kill a child, and how to tell them apart.
