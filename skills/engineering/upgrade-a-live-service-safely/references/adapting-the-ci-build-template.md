# Adapting `templates/ci-standalone-build.yml` to a real project

The template is deliberately generic. These are the facts you must gather from
the **live host** before filling it in, and the traps found while adapting it to
the router (2026-08-01).

## Gather the target facts first — from the running unit, not from docs

```bash
ssh host 'bash -s' <<'EOF'
systemctl --user show <svc> -p MainPID -p WorkingDirectory -p EnvironmentFiles -p ExecStart --value
grep -E "^PORT=|^DATA_DIR=" ~/src/<App>/.env
ls -l ~/src/<App>/current            # is a release symlink already in place?
ls -1 ~/src/<App>/releases | tail -5
node --version; uname -m
which gh                             # needed for `gh run download` on the host
df -h /home | tail -1                # room for another ~5 GB release?
EOF
```

Each of these changes the workflow or the stage script:

| Fact                          | Why it matters                                                                                                                                                     |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `WorkingDirectory`            | If it already ends in `current/...`, cutover is a symlink flip and the unit needs no edit. If it points at a real dir, that's a one-time unit change.              |
| `PORT` from `.env`            | The live port. Your smoke port must differ (e.g. live 20128 → test 20129). Do **not** assume 3000 — probing the wrong port returns `000` and looks like an outage. |
| `DATA_DIR`                    | The DB location to `sqlite3 .backup` from.                                                                                                                         |
| `node --version` + `uname -m` | Pin `node-version:` and pick `ubuntu-24.04-arm` vs `ubuntu-24.04`.                                                                                                 |
| `gh` present on host          | The stage script downloads the artifact host-side.                                                                                                                 |
| free disk                     | Releases are large; keep 2–3 and prune with the running-release guard.                                                                                             |

## Runner selection

`ubuntu-24.04-arm` is free only on **public** repos. Check with
`gh repo view OWNER/REPO --json isPrivate` — note the field is `isPrivate`;
`visibility` is not a valid field and errors out with a field list.

## Never call the project's release script in CI either

Use `npm run build`, not `npm run build:release`. The release script typically
begins `rm -rf .build dist`. In CI that's merely wasteful, but keeping the same
command in both places prevents the muscle memory that causes the on-host
outage. Pass `APP_BUILD_SHA=$(git rev-parse --short HEAD)` explicitly since
you skipped the wrapper that normally sets it.

## The two asserts that make the artifact trustworthy

1. **Bundler assert** — grep the tee'd build log and fail the job if the banned
   bundler appears. The env guard alone has been observed _not_ to hold through
   the project's own scripts.
2. **Fork-fix-present assert** — grep the emitted standalone bundle for a symbol
   unique to your patch:
   ```yaml
   if grep -rqs "<OLD_FIX_SYMBOL>" .build/next/standalone 2>/dev/null; then
     echo "OK: fix present in bundle"
   else
     echo "::error::fork fix missing from bundle"; fail=1
   fi
   ```
   This catches the case where the build succeeded but from the wrong ref. Use
   the _same_ marker string in `stage_and_smoke.sh` so host-side staging
   re-verifies it independently.

Also assert no `sharp-darwin-*` and that `*.node` files exist at all — an empty
native-module set means the rebuild step silently no-opped.

## Lint before pushing; the workflow file has its own gate

```bash
actionlint .github/workflows/standalone-build.yml
shellcheck -S style stage_and_smoke.sh
bash -n stage_and_smoke.sh
python3 -c "import yaml;yaml.safe_load(open('.github/workflows/standalone-build.yml'))"
```

Pushing a workflow file needs a token with `workflow` scope —
`gh auth status` prints scopes. A `push:` trigger on the branch fires the run
automatically; `gh workflow run` 404s until the file exists on the default branch.

## Watching the run gives you real verification before it finishes

`gh run view <id> --json jobs --jq '.jobs[].steps[]'` shows per-step status.
Steps completing (`checkout`, `setup-node`, `npm ci`, `npm rebuild`) are live
proof the workflow file is valid and its install flags work — stronger evidence
than actionlint. Report that honestly rather than claiming the whole pipeline
passed, and name which steps remain gated behind the long compile.
