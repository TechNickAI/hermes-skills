# Runner lessons — one occasion

## Search limits must be configurable end to end

A seven-day scan across two active orgs found 38 merged PRs. The packaged scanner still had `--limit 60` hardcoded even though the skill's documented default is `SEARCH_LIMIT=200`. This could silently omit older PRs on busier runs.

Reusable rule:

- Declare `SEARCH_LIMIT` beside the scanner's other knobs.
- Pass `str(SEARCH_LIMIT)` to `gh search prs --limit`.
- Run the search with failure checking enabled.
- Warn when the discovered count equals the limit; equality means the result set may have been truncated and the limit should be raised.

The packaged `scripts/triage_scan.py` was updated accordingly.

## Extract comment inventories without transporting full bot bodies

Review-bot comments can contain very large markdown bodies, embedded image data, and control characters. Pulling complete `gh api` JSON through a shell/tool output boundary and then applying `json.loads` failed during this run. The durable approach is to project only the fields needed for triage at the API boundary:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments \
  --jq '.[] | [(.id|tostring),.user.login,.path, (.line //.original_line // 0), (.body | gsub("[\\r\\n\\t]+"; " "))] | @tsv'
```

Use the analogous issues endpoint for general PR comments. For counting, keep using server-side `--jq '[.[] | select(...)] | length'`; do not transport full bodies at all. If prose is needed, truncate it after TSV projection.

## Final verification should be independent of runner summaries

After the serial dispatcher exits:

1. Read the incremental results file and require one result per selected PR.
2. Re-run the live zero-reaction query for every original PR rather than trusting Claude's prose or cached runner counts.
3. Verify every reported follow-up via `gh pr view {number} --repo {owner}/{repo}` and confirm it is open and has the configured label.
4. Confirm each JSONL has a positive Skill-tool count.
5. Confirm both supported workspace roots have no remaining `*pr-sweep*` directories.

This catches stale output, misidentified PR links, labeling failures, and cleanup drift while keeping the final report evidence-based.
