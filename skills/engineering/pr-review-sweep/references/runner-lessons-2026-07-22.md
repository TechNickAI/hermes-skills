# Runner lessons — 2026-07-22

Session-specific evidence from a 20-PR scan that triaged 28 zero-reaction candidates on two merged PRs and produced two follow-ups.

## Two closure systems must both be checked

The original merged PR's zero-reaction query and the follow-up PR's GitHub review-thread state answer different questions:

- **Original closure:** root review/issue comments have an author reply or reaction, so the nightly sweep will not rediscover them.
- **Follow-up merge pressure:** every `reviewThreads.nodes[].isResolved` is true, so no bot finding remains open on the fix PR.

A reply plus 👍 can make the first query return zero while leaving the GraphQL thread unresolved. Before auto-merge, query `reviewThreads` independently, substantively address each finding, explicitly resolve it, and query again immediately before merging.

A green bot check is not enough: one follow-up had `claude-review=SUCCESS` while Codex had posted a valid unresolved inline finding. The follow-up was fixed in one second push, the author replied with commit/test evidence, and the thread was then resolved. This remained within the two-iteration churn guard.

## Gate evidence from this run

- A small money-path follow-up (33 changed lines, four files) was eligible only after real `pytest`, Claude review, and Bugbot checks passed and unresolved threads reached zero. Its changes were compared to the exact original review requests before squash-merging.
- Another small follow-up remained open despite successful bot checks: real Python tests and lint failed, one Codex thread remained unresolved, and the diff modified GitHub workflow configuration. Workflow/config changes independently fail the small-change auto-merge gate.
- Final verification re-ran the original zero-reaction queries, fetched follow-up state/checks/thread counts from GitHub, and confirmed global cleanup left no `*pr-sweep*` directories.

## Reporting

The final auto-merge table should expose gate evidence, not only a yes/no decision: ownership/label, diff size and file count, real CI, bot checks, unresolved-thread count, money-path/config scrutiny, merge result, and why an open PR was held.
