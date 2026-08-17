# PR review sweep runner lessons — 2026-07-11

Condensed operational lessons from a successful 10-PR sweep across `example-org` and `TechNickAI`.

## Scan sizing

- `gh search prs --limit 50` was too low for a 7-day window across active orgs: it found only 50 PRs, while `--limit 200` found 96.
- Treat `SEARCH_LIMIT=200` as the default and report whether the discovered count hit the cap. If it does, raise the cap or split by org/date.
- The one-pass Python/`execute_code` scanner stayed practical at 96 PRs: two `gh api` calls per PR completed in about a minute and produced a compact flagged table.

## Dispatcher shape

A Python serial dispatcher worked well when the bundled script path was not readily available:

1. Read `/tmp/pr_review_sweep_scan.json`.
2. Select `flagged[:MAX_PRS_PER_RUN]` after exclusions.
3. For each PR:
   - clone to the resolved writable `SWEEP_ROOT`;
   - create branch `pr-sweep-{pr}`;
   - run `claude --print --model sonnet --dangerously-skip-permissions <prompt>` in the workspace;
   - capture stdout/stderr to `/tmp/pr-review-sweep-logs/{owner}-{repo}-{pr}.log`;
   - find the current JSONL via `~/.claude/projects/*{repo}-pr-sweep-{pr}*/*.jsonl`;
   - verify `"name":"Skill"`, `address-pr-comments`, and `pr-link` markers;
   - label follow-up PRs `review-sweep`;
   - re-query original PR unhandled comments until `0`;
   - cleanup the workspace immediately and globally at the end.

## PR-link duplication

Claude Code can emit multiple identical `pr-link` markers for the same follow-up PR in one session. Deduplicate by `(prNumber, prUrl)` before reporting or labeling. Duplicate labeling is harmless but clutters result JSON.

## Process behavior

- `process(wait)` may clamp to 60s; repeated timeouts are normal while a tracked sweep process is healthy.
- A sub-agent can show a `pr-link` and close the original comments before its stdout summary appears. Let it exit naturally unless it is clearly stuck in a CI-poll tail.
- If you implemented your own subprocess runner inside one tracked Hermes background process, `process(action=kill, session_id=...)` kills the whole dispatcher, not just the current nested Claude. Prefer letting the nested process exit, or design the runner to expose/handle per-PR termination itself.

## Final verification

After the dispatcher exits, run a compact verification pass:

- summarize `/tmp/pr_review_sweep_results.json`;
- `gh pr view <followup> --repo <owner/repo> --json state,isDraft,labels,url,headRefName,title` for each unique follow-up;
- verify all follow-ups are open, non-draft, and labeled `review-sweep`;
- verify no `~/dev/*pr-sweep*` or `~/pr-sweep-workspaces/*pr-sweep*` dirs remain.
