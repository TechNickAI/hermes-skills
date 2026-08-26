# Reading CURRENT main, and the OPEN-but-rotting PR

Two traps that sit _before_ the CLOSED≠FIXED check in the main skill, plus the
tooling recipes that actually worked. Source session: one occasion, H‍ermes gateway
progress-message cleanup (the "wall of text" UX complaint).

## Trap 1 — diagnosing "unfixed upstream" from a STALE local checkout

Step 1 of the main skill catches _patching_ a tree nothing runs. This is the
twin: **reading** a tree that is behind, and concluding from it that a bug is
still present on `main`.

Live example. `~/.h‍ermes/h‍ermes-agent` HEAD was `<sha>`, dated
**one occasion**. Actual upstream `main` was `<sha>`, dated **one occasion** —
seven days and ~90 new lines in the one file under investigation
(`gateway/stream_consumer.py`: 2347 lines local vs 2437 on main).

The verdict happened to survive re-checking, but it was _luck_. On a repo merging
~1,400 PRs per release, a week-old checkout is a different codebase. Announcing
"still broken on main" from it is an unforced error.

**Rule: never cite a local checkout as evidence about upstream state.** Establish
the delta first, in two cheap commands:

```bash
cd ~/.h‍ermes/h‍ermes-agent && git log -1 --format='%h %ci'
gh api repos/NousResearch/h‍ermes-agent/commits/main --jq '.sha[0:10] + " " +.commit.committer.date'
```

If they differ, fetch the real file before forming any conclusion.

## Trap 2 — the OPEN PR that is exactly your fix, and is rotting

The main skill covers CLOSED≠FIXED. The mirror trap: an **OPEN** PR that already
implements your fix, looks alive, and is functionally dead.

Live example — PR #22613, `feat(gateway): cleanup_progress polish`:

| Field           | Value                               |
| --------------- | ----------------------------------- |
| state           | `open` (not draft)                  |
| mergeable       | `false` / `dirty`                   |
| size            | +550/−20 across 6 files, 12 commits |
| created         | one occasion                        |
| last touched    | one occasion                        |
| review comments | **0**                               |

Commit 2 was literally _"expose commentary_message_ids + redirect hook — captures
successful `_send_commentary` ids"_ — the exact fix under design. Finding it
prevented reinventing 550 lines of tested work, **and** finding its state
prevented the opposite error of assuming a fix was inbound.

**The diagnostic set — all four fields, never just `state`:**

```bash
gh api repos/NousResearch/h‍ermes-agent/pulls/<n> \
  --jq '{state,draft,mergeable,mergeable_state,created:.created_at,updated:.updated_at,
         adds:.additions,dels:.deletions,files:.changed_files}'
```

`open` + `dirty` + months of silence + zero review comments = abandoned. Treat it
as prior art to cite and credit, not as a fix that is coming.

**Why big bundles rot — and the lesson for our own PR.** #22613 mixed six
concerns (queue-merge fix, commentary IDs, bubble coalescing, approval-ack
cleanup, cross-restart persistence, mono formatting) into one 550-line diff. The
repo's own `AGENTS.md` says it merges `fix(...)` PRs against a _single_ reported
symptom. A narrow ~15-line fix in the existing mechanism is far more mergeable
than a well-tested mega-bundle. **Ship the narrow PR; cite the bundle for
credit.**

## Search open PRs, not just issues

Feature-gap prior art lives in PRs more often than issues. Issue search alone
missed #22613 entirely; `gh pr list --state open --search` found it. Sweep
several phrasings and dedupe by number:

```python
seen = {}
for q in ["cleanup_progress", "commentary delete", "progress bubble cleanup", "interim assistant"]:
    r = terminal(f'gh pr list --repo NousResearch/h‍ermes-agent --state open '
                 f'--search {json.dumps(q)} --limit 15 '
                 f'--json number,title,updatedAt,author')
    for p in json.loads(r["output"]):
        seen[p["number"]] = (p["title"], p["updatedAt"][:10], p["author"]["login"])
```

Four queries returned 39 unique open PRs touching the area. Also check whether a
maintainer _believes_ the feature shipped: #21252 was closed as "implemented in
#21186" when #21186 wired only three of four message classes. **A maintainer's
"implemented" closure is a claim about scope, not proof of completeness** —
verify which code paths it actually covered.

## Tooling recipes that worked (and the ones that don't)

**Fetching one file at current main — works for normal files:**

```bash
gh api repos/NousResearch/h‍ermes-agent/contents/<path>?ref=main \
  -H "Accept: application/vnd.github.raw" > /tmp/file.py
```

**…but returns EMPTY on very large files.** `gateway/run.py` (29,734 lines)
produced a 0-line file, and the `--jq '.content' | base64 -d` variant failed with
`error decoding base64 input stream`. Both fail _silently enough_ to look like a
missing file. **Always `wc -l` the result before trusting it.**

**Fallback for large files — sparse clone.** This is the reliable path when the
contents API gives you nothing:

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/NousResearch/h‍ermes-agent.git hm-main
cd hm-main && git sparse-checkout set gateway     # NO -q flag
```

⚠️ `git sparse-checkout set <dir> -q` **exits 129** — `-q` is not a valid switch
for that subcommand, unlike most git commands. Drop it.

**`gh api.../files --paginate` breaks `json.loads`.** Pagination concatenates
multiple JSON arrays, giving `JSONDecodeError: Extra data: line 1 column 277`.
Use an explicit page size instead:

```bash
gh api "repos/NousResearch/h‍ermes-agent/pulls/<n>/files?per_page=100"
```

**The Projects-classic GraphQL error is still live** (confirmed one occasion, on
both `gh issue view --comments` and `gh pr view`):

```
GraphQL: Projects (classic) is being deprecated... (repository.issue.projectCards)
```

Fall back to `gh api repos/.../issues/<n>` and
`gh api repos/.../issues/<n>/comments`. The main skill calls this intermittent —
it was 100% reproducible this session. Never read a `gh... view` failure as
"the issue doesn't exist."

## Verification checklist for this reference

- [ ] Local checkout HEAD date compared against upstream `main` before any claim
- [ ] Decisive file re-fetched from `main`, and `wc -l` confirms it's non-empty
- [ ] Open PRs searched (multiple phrasings), not just issues
- [ ] Any candidate PR checked for `mergeable_state`, age, and review-comment count
- [ ] "Implemented in #X" closures verified against the code paths actually covered
- [ ] Our own contribution scoped narrow, with prior-art PR cited for credit
