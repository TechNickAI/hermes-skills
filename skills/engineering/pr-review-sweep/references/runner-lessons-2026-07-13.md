# Runner lessons — one occasion

Session context: nightly PR review sweep across `carmentacollective` and `TechNickAI`, lookback 7 days, max 10 PRs, excluding `TechNickAI/openclaw-config`. Scanned 91 merged PRs, found 22 flagged PRs, processed 10, opened three follow-up PRs, and verified every processed original PR at zero residual unhandled comments.

## Durable lessons

### Treat reactions as the operational closure signal

The human-facing description may say "no author reply, zero reactions," but the runnable sweep heuristic is root non-author comments with zero reactions. Do **not** suppress a root review comment just because the PR author replied somewhere in the thread. Author replies are useful context for the sub-agent, but a zero-reaction root comment still re-flags on the next sweep unless it is reacted to.

Practical rule:

```python
line_roots = [
    c for c in line_comments
    if login(c) != author
    and c.get("in_reply_to_id") is None
    and reaction_count(c) == 0
]
issue_comments = [
    c for c in issue_comments
    if login(c) != author
    and reaction_count(c) == 0
]
```

If an earlier discovery table used "no author reply" filtering, expect the sub-agent to find more comments than the table showed. The authoritative success check remains the post-run zero-reaction query returning zero.

### Packaged scripts live with the skill

`triage_scan.py` and `run_pr_review_sweep.py` are packaged linked files for this skill, not necessarily visible under the current working directory or `~/src`. Load them via `skill_view(name="pr-review-sweep")` and its `linked_files`, then access with `skill_view(name="pr-review-sweep", file_path="scripts/run_pr_review_sweep.py")` (or run/copy from the installed skill directory). Do not infer they are absent from a repo-level file search.

### Final report shape that worked well

The useful report included:

- scanned count, flagged count, processed count, deferred count;
- confirmation that `address-pr-comments` Skill usage was verified from Claude JSONL for each processed PR;
- follow-up PR links and labels;
- tracking issue links, if any;
- per-processed-PR table: initial unhandled, outcome, follow-up artifact, final unhandled;
- deferred PR list with counts;
- workspace cleanup/orphan status;
- explicit "No merges performed."

This gave the user enough operational detail without dumping Claude transcripts.

## Session-specific artifacts created

- `TechNickAI/hermes-config#63` — follow-up PR for `--recency-days 0` handling.
- `carmentacollective/<agent-f>#47` — follow-up PR for MQS pending-backfill summary.
- `carmentacollective/<agent-f>#48` — tracking issue for persistent 429 pagination stalls.
- `carmentacollective/fiddler#60` — follow-up PR for preserving no-orders-after-fill invariant after state-write failure.

Do not hard-code these artifact numbers into future sweeps; they are examples of the report content, not reusable targets.
