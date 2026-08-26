# Fork patch custody and live-artifact proof

Use this when an owner maintains a fork primarily to carry one or more production-critical patches while rebasing onto upstream release branches.

## The failure chain this prevents

A fork-specific patch can remain visible on an old branch while disappearing from the current release branch. Configuration may still contain the patch's environment variable, creating a convincing but inert setup. A health endpoint can stay green because the service works without the intended behavior.

Treat these as separate truths:

1. **Patch exists somewhere in the fork.** Insufficient.
2. **Current release branch contains the patch semantics.** Required for the next build.
3. **Built artifact contains the patch.** Required for deployment.
4. **Running process uses that artifact and executes the configured path.** Required for live truth.

## Before cleaning or rebasing a fork

1. Establish the fork's purpose from README, prior PRs, release branches, deployment configuration, and owner statements.
2. Enumerate fork-only commits across **all remote branches**, not only the current release delta:
   ```bash
   git log --all --oneline --decorate --not --remotes=upstream
   git branch -r --contains <known-patch-sha>
   gh pr list -R OWNER/REPO --state all --limit 100
   ```
3. Make a custody table for each required patch:
   - behavior/invariant
   - original commit/PR
   - current release carrier commit
   - focused test
   - artifact marker or runtime probe
4. Do not call a fork "clean" until every required semantic patch is either carried on the active release branch or explicitly retired by the owner.
5. Keep owner CI/ops plumbing out of the application fork when appropriate, but never confuse workflow cleanup with permission to drop application behavior.

## Verify semantics, not only commit ancestry

Cherry-picking changes the commit SHA. After a cherry-pick or conflict-resolution commit, this can legitimately print `no`:

```bash
git merge-base --is-ancestor <original-sha> <release-ref>
```

Use several proofs instead:

```bash
# Compare patch identity when applicable
git show <original-sha> | git patch-id --stable
git show <carrier-sha> | git patch-id --stable

# Confirm the behavior symbols and focused test on the release ref
git show <release-ref>:path/to/source | grep '<feature-symbol>'
git show <release-ref>:path/to/test >/dev/null

# Inspect the release delta and PR merge
 git log --oneline <upstream-release>..<fork-release>
 gh pr view <number> -R OWNER/REPO --json state,mergedAt,mergeCommit
```

Report: "original SHA is not an ancestor because it was cherry-picked; release carries equivalent code in `<carrier>`" rather than implying the patch is absent.

## Prove the live server separately

Work outward from the process actually serving traffic:

1. Confirm a real user-shaped request succeeds during the investigation.
2. Read the service manager's actual working directory and environment file.
3. Resolve the running release symlink and build identity.
4. Search the **deployed bundle/artifact**, not merely the source checkout, for the feature symbol.
5. Verify the configuration value is read by deployed code. An env line without its reader is inert.
6. If feasible, exercise the outbound behavior or inspect a safe wire-level trace. Health `200` does not prove the patch executes.

Example result shape:

- **Fork release:** carries feature symbol + focused test in carrier commit X.
- **Production config:** requests the feature (`SETTING=value`).
- **Running artifact:** lacks the reader, so the setting is inert.
- **Service availability:** healthy and serving, but not with the fork behavior.

Do not deploy merely because the custody audit found drift. Restoring the fork branch is reversible and can proceed; production cutover remains a separate approval-gated operation with artifact smoke test, DB snapshot if migrations exist, atomic switch, and rollback.

## CI and review gates

- Run the focused behavior test under both default and configured modes.
- Run the project typechecker.
- Read automated inline review comments after each push; stale comments may describe an earlier commit.
- Test that the override does not leak into adjacent API-key/static-registry paths.
- Test late header/config merges so the intended paired fields cannot be split after construction.
- Build the exact active release ref and assert the feature marker inside the resulting artifact before considering deployment.
