# Runner lessons — one occasion

## A zero-reaction hit is a triage candidate, not proof of a defect

The mechanical query surfaced three merged PRs. Two hits were positive issue-level reviews saying the changes were correct and complete; only one PR had actionable feedback. Before dispatching Claude, classify every hit against both the comment body and the current merged code.

Reusable outcomes:

1. **Fix required** — the concern still exists in the merged head. Dispatch `address-pr-comments` and create a labeled follow-up.
2. **Already self-healed** — later commits or related work already implement the requested behavior. Reply with concrete code-path evidence and react; do not duplicate the fix.
3. **Positive review / no change requested** — acknowledge that the review found no issue and react; do not dispatch a coding agent.
4. **Deliberate design choice / incorrect finding** — explain the evidence and react.

The scan heuristic is intentionally broad. Triage is what converts candidates into work. After closing no-change hits, re-run the live zero-reaction query rather than trusting the posting commands.

For issue comments, reactions use:

```bash
gh api -X POST repos/{owner}/{repo}/issues/comments/{comment_id}/reactions \
  -f content='+1'
```

For inline review comments, use the pull-comment reaction endpoint and post an inline reply tied to the root comment.

## Inspect the merged implementation before accepting old feedback

A bot claimed chart rendering replaced the destination before verifying the new PNG. The current merged implementation had already been refactored to write to `mkstemp`, verify the temporary PNG, and only then call `os.replace`. Reading the current code prevented a redundant or regressive follow-up.

When a review comment predates the final merged commit:

- inspect the exact merged code path;
- trace helper calls rather than judging only the commented line;
- cite the verification and replacement order in the reply;
- treat the original comment as self-healed when the final implementation already satisfies it.

## A review-bot pass is not real CI

A small follow-up had a successful Cursor Bugbot check, zero review threads, a clean merge state, and local `py_compile` success. The repository had no Actions workflows providing lint and tests. Under a policy requiring real CI (`lint + tests`), this is **not** enough to auto-merge.

Gate interpretation:

- Review-bot success satisfies the bot-review gate only.
- Local syntax checks are useful evidence but do not substitute for repository CI.
- Inspect `statusCheckRollup`, `gh pr checks`, and the repository's Actions workflows.
- If there is no real lint/test workflow, report the CI gate as unavailable and leave the PR open.
- Never reinterpret "all existing checks passed" as "required CI exists and passed."

Recommended report wording: `Bot review passed and threads are clear, but the repository exposes no real lint/test CI; left open.`

## Clone fallback must run branch creation inside the clone

This command shape is unsafe when the shell's working directory remains the parent directory:

```bash
gh repo clone owner/repo /path/repo-pr-sweep-1 && git checkout -b pr-sweep-1
```

The clone succeeds, then `git checkout` runs outside a Git repository. Use either:

```bash
gh repo clone owner/repo /path/repo-pr-sweep-1
git -C /path/repo-pr-sweep-1 checkout -b pr-sweep-1
```

or make branch creation a separate terminal call with `workdir` set to the clone. Verify with `git -C <clone> status --short --branch` before dispatch.

## Reaction inventory: avoid `to_entries` on the reactions summary

REST's `.reactions` object includes `total_count` alongside reaction-name fields. Applying `to_entries` and selecting values mechanically can accidentally print `total_count` as though it were a reaction type. For closure, use `.reactions.total_count`. If exact reaction kinds matter, select known reaction fields explicitly or use GraphQL `reactionGroups`.
