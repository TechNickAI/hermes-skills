# Runner lessons — one occasion

Session context: nightly PR review sweep across `carmentacollective` and `TechNickAI`,
lookback 7 days, max 10 PRs, excluding `TechNickAI/openclaw-config`. Scanned 68 merged
PRs (65 after exclusions), found 7 flagged, triaged 5 as self-healed/trivial (handled
directly by orchestrator with reply+react), dispatched 2 to Claude Code, opened 2
follow-up PRs. All 7 PRs verified at zero residual unhandled comments.

## Durable lessons

### Triage-before-dispatch eliminates most flagged PRs

The Contents-API validation step (already in the skill) is highly effective at catching
self-healed findings before provisioning a Claude Code workshop. In this run, 5 of 7
flagged PRs (71%) were dismissed as self-healed or deliberate design choices:

- **antevorta #42** (7 comments): All 6 bot findings already fixed in merged code —
  `ttl<=0` bypass, `_safe_int` for Redis port, `_resolve_ttl` honors explicit 0 without
  `or` operator, ping failure sets client to None, `redis>=5.0` in pyproject optional deps.
  Three different bots (cursor, gemini, codex) all reviewed an earlier revision.
- **<agent-f> #63** (1 comment): Merged code already used `{wh:g}` — bot reviewed earlier push.
- **<agent-f> #37** (1 comment): Author deliberately kept redundant `CODMAP` + `COD` with
  explanatory comment "keep both for clarity" — declined as deliberate design choice.
- **fiddler #42** (1 comment): Gemini said "unable to generate a review" — no finding at all.
- **cryptoai #793** (3 comments): Positive claude[bot] reviews — reviewer explicitly said
  "Not asking for the guard back — just flagging."

All 13 comments on these 5 PRs were closed with a contextual reply + 👍 reaction in a single
`execute_code` batch (16 seconds total), then verified clean. This is 5x faster than
dispatching Claude Code per PR and far cheaper.

### Batch reply+react for all self-healed PRs in one execute_code pass

When multiple PRs need orchestrator-only closure (reply + react, no code changes), batch
ALL of them in a single `execute_code` block rather than serial-looping `terminal` per PR.
The function pattern:

```python
def reply_line_comment(owner, repo, pr, comment_id, body):
    # POST pulls/{pr}/comments/{id}/replies
    # POST pulls/comments/{id}/reactions (note: no {pr} in reaction path)

def reply_issue_comment(owner, repo, pr, comment_id, body):
    # POST issues/{pr}/comments (fresh top-level, no threaded reply endpoint)
    # POST issues/comments/{id}/reactions (DIFFERENT path from pulls/comments)
```

Both the three-endpoint-shape distinction and the batching approach are already in the
skill, but the key realization is that the ENTIRE self-healed batch (5 PRs, 13 comments)
takes ~16 seconds in one `execute_code` pass — vs. minutes of `terminal` round-trips.

### Hand-dispatch is correct for small dispatch counts

With only 2 genuine issues after triage, hand-constructing the clone → checkout →
background-dispatch → poll → verify → cleanup loop was straightforward and took ~4 minutes
per PR (including Claude Code execution). The serial dispatcher script's setup overhead
(scan JSON format, env knobs, results file) isn't justified for ≤4 dispatches. The skill
now carries the threshold guidance: ≥5 → use dispatcher; ≤4 → hand-dispatch.

### Deliberate design choices should be declined, not "self-healed"

When the author explicitly commented WHY a flagged pattern exists (e.g. <agent-f> #37's
`# (prefix "COD" covers KXCODMAP + KXCODGAME; keep both for clarity)`), the correct
orchestrator response is to decline the finding with an explanation — not to label it
"self-healed." The reply should reference the author's own comment as evidence the
pattern is intentional. This is a third outcome category beyond "self-healed" and
"genuine issue": "declined as deliberate design choice."

## Session-specific artifacts created

- `carmentacollective/<agent-f>#71` — follow-up PR for bracket escaping in Telegram Markdown links.
- `carmentacollective/fiddler#64` — follow-up PR for misleading log value rename + dead code removal.

Do not hard-code these artifact numbers into future sweeps; they are examples of the
report content, not reusable targets.
