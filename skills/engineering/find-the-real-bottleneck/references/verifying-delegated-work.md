# Verifying delegated work

A subagent's summary is a **self-report, not evidence**. Two real outcomes from
one occasion, same session, both requiring independent verification.

## Case A — timed out, no summary, but the work was correct

Delegation `deleg_1326af72` (UX review + combo descriptions) hit the 1200s
timeout after 33 API calls and returned **no summary at all**.

Wrong reaction: assume nothing happened and re-dispatch. Right reaction: check
the artifacts.

```bash
cd <project>
git status --short                      # empty — but the dir wasn't a git repo
find <project> -type f -mmin -30 \
  -not -path "*/node_modules/*" -not -path "*/.git/*"
```

Five files had been modified. The work was ~complete; only the summary was lost.

Then verify **content correctness against ground truth**, not against the
subagent's claims:

```bash
# 1. does the artifact contain what was asked for?
python3 -c "import json; d=json.load(open('data/rationale.json'));..."

# 2. is it FACTUALLY right? read the source of truth independently
ssh host 'node -e "...read the real config table..."'

# 3. is it actually LIVE, not just on disk?
curl -s https://<live-url> | grep -oiE "<expected new strings>"
```

Result: all three descriptions were accurate, and the subagent had **corrected
my briefing** — I'd said a combo "routes to xAI" without detail; it found the
paid second rung and documented it. A timed-out agent can still outperform your
own brief.

**Caveat worth reporting to the user:** with no self-report and no git history,
you cannot confirm it took backups or what else it touched. Say that plainly
rather than implying a clean run.

## Case B — confident summary, wrong conclusion

An earlier delegation returned a tidy theory ("VACUUM runs in a loop, the file
drops to 0 bytes"). Checking its evidence:

```bash
sudo lsof <dbfile>              # exactly ONE process, not a loop
sqlite3 <dbfile> "PRAGMA auto_vacuum;"   # 0 — disabled
stat -c%s <dbfile>              # size only ever grows
```

The theory was false; the "0 bytes" readings were `stat` racing a writer.

## Checklist

1. **Did it change anything?** `find -mmin`, `git status`, directory mtimes.
2. **Are the claims true?** Re-read the source of truth yourself — the DB, the
   config, the API — never the subagent's restatement of it.
3. **Is it live?** On-disk ≠ served. `curl` the real URL, hit the real endpoint.
4. **Did it verify or assert?** Look for real command output in the transcript
   (`cache/delegation/live/<id>/task-N.log`). Confident prose with no output is
   a theory.
5. **What can't you confirm?** Backups, side effects, files touched outside
   scope. Report the gap.

## Briefing rules that reduce rework

- Give the subagent the **exact read command** for ground truth, including known
  quirks (e.g. "this DB intermittently throws `database disk image is malformed`
  — that's a transient torn read, retry up to 10x").
- Name the shell requirement explicitly when the login shell differs
  (`ssh host 'bash -s' <<'EOF'` for zsh hosts) and the noise filter to apply.
- Say **which layer to edit**: "edit the SOURCE that generates the page, not the
  built output, or the next sync overwrites it."
- Require negative reporting: "if something fails or you cannot verify it, say
  so plainly — never fabricate a result."
- Keep scope to a specific file/function/question. Open-ended "explore this repo
  and report back" is the shape that burns the full timeout with nothing to show.
