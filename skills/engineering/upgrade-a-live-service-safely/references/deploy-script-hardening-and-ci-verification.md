# Deploy-script hardening and CI verification

Standing up a deploy script on a NEW host, and proving it works before merging.
Worked end-to-end on the a trading agent the co-tenant host → trading.<internal-domain> cutover, one occasion.

The governing rule: **run the deploy against the real host before merging it.**
Seven distinct bugs were found in a script that read correctly, passed
`bash -n`, and had been reviewed. Every one of them surfaced only by execution.

---

## The `set -euo pipefail` bug family

A deploy script that dies silently mid-run — production stopped, tree not
updated, no error text — is the worst possible failure shape. Three separate
mechanisms produced exactly that in one script.

### 1. `pipefail` makes an empty `pgrep` fatal

`pgrep` exits **1 when nothing matches**, which during a deploy is the EXPECTED
healthy state. Under `set -o pipefail` the whole pipeline inherits that status
even though every other stage succeeded, and `set -e` kills the script at the
assignment.

```bash
# FATAL under set -euo pipefail when nothing matches:
running=$(pgrep -f "worker_|runner_" | wc -l)

# CORRECT — swallow only pgrep's status, inside braces:
running=$( { pgrep -f "worker_|runner_" || true; } 2>/dev/null | wc -l | tr -d '[:space:]')
running=${running:-0}
```

`|| true` inside the braces neutralizes pgrep specifically, leaving a genuine
`wc`/`tr` failure still able to fail the pipeline.

### 2. `[ cond ] && cmd` as the last command in a block

When the condition is FALSE the AND-list exits 1. If it is the last command in a
loop body or function, that becomes the block's status and `set -e` terminates
the script.

```bash
# FATAL when $running != 0:
while...; do
    ...
    [ "$running" -eq 0 ] && break
done

# CORRECT:
    if [ "$running" -eq 0 ]; then
        break
    fi
```

Same trap in failure-path restore lines (`[ "$PAUSED" = 1 ] && start_service`) —
they silently skip the _next_ restore when the first condition is false.

### 3. `pgrep -fc... || echo 0` yields the string `"0\n0"`

`pgrep -fc` prints a count AND exits 1 on no match, so the `|| echo 0` appends a
second line. Every later `[ "$x" -eq 0 ]` dies with
`integer expression expected`, the break never fires, and the loop burns its full
timeout before a FALSE refusal. Count lines instead of using `-fc`.

**Diagnostic method for all three:** `bash -x` the script and read the last few
lines. The tell is an assignment immediately followed by `rc=1`, trap, exit.
Then reduce to a standalone repro — a 10-line script with the same
`set -euo pipefail` + trap preamble — rather than re-reading the original.

---

## Virtualenv and interpreter traps

### `source activate` inherits a stale `VIRTUAL_ENV`

Activation only prepends `PATH` and exports `VIRTUAL_ENV`. Tooling (`uv`, `pip`)
happily picks up whatever `VIRTUAL_ENV` the _calling_ shell already had — so a
leftover value from an operator session makes the deploy fail against an
interpreter that no longer exists, while the real venv is healthy.

```bash
unset VIRTUAL_ENV
VENV_PY="$VENV/bin/python"
[ -x "$VENV_PY" ] || { echo "No interpreter at $VENV_PY"; exit 1; }
uv pip install -q --python "$VENV_PY" -r requirements/requirements.txt
```

Use the explicit interpreter for the **verification step too**. A bare `python`
after removing activation either fails or — far worse — verifies imports against
the SYSTEM interpreter, proving nothing about what production runs.

### A requirements-path miss installs NOTHING and reports success

```bash
if [ -f requirements.txt ]; then...
elif [ -f pyproject.toml ]; then...
fi          # <- both miss when the repo pins under requirements/
```

The step no-ops and the deploy reports success while shipping whatever was
already in the venv. Always add a terminal `else` that FAILS:

```bash
else
    echo "No requirements file found. Refusing to deploy blind."
    exit 1
fi
```

### The interpreter must not live inside a human's home directory

A uv-managed Python under `/home/<person>/.local/share/uv/...` is unreachable to
the deploy user when that home is `0750` — and production's runtime then depends
on one human's home surviving. Install it to the shared state volume:

```bash
export UV_PYTHON_INSTALL_DIR=/srv/<app>/shared/python
uv python install "$(cat.python-version)"
uv venv --python "$PYVER" /srv/<app>/shared/venv.new    # build BESIDE, then swap
```

Assert the result before swapping — `readlink -f venv.new/bin/python3` must be
under the shared path — then move the old venv aside rather than deleting it.

---

## Deploy-user permission architecture

Keeping the prod tree owned by a non-login user (so the human's account cannot
write it) is correct, and creates four concrete requirements:

1. **CI logs in as the human account, so grant one scoped sudo command:**

   ```
   ubuntu ALL=(deploy-user) NOPASSWD: /bin/bash /srv/app/ops/deploy_wrapper.bash *
   ```

   One command, no shell, no general sudo.

2. **The deploy user needs sudo BACK to control services it does not own**
   (systemd _user_ units and pm2 belong to the human account):

   ```
   deploy-user ALL=(ubuntu) NOPASSWD: SETENV: /usr/bin/systemctl, /usr/bin/pm2
   ```

   `SETENV:` is required — `systemctl --user` needs `XDG_RUNTIME_DIR` to find the
   user manager, and sudo strips it by default:

   ```
   sudo: sorry, you are not allowed to set the following environment variables: XDG_RUNTIME_DIR
   ```

   In the script: `XDG_RUNTIME_DIR="/run/user/$(id -u "$GATEWAY_USER")"`.

3. **Shared tooling belongs in `/usr/local/bin`**, not a user's `~/.local/bin`.

4. **Git refuses to operate on a tree owned by another user** — an _ownership_
   check, not permissions, and the error names `.git` rather than the cause:
   ```bash
   git config --global --add safe.directory /srv/app
   git config --global --add safe.directory /srv/app/.git
   ```

Also: any state file the deploy WRITES (a `DEPLOYED_SHA` marker) must be owned
by the deploy user. Creating it as the human account during setup produces a
`Permission denied` at the very last step of an otherwise successful deploy.

---

## Test the deploy by RUNNING it, before merge

Do not wait for merge to find out. Exercise the real wrapper via the same
sudoers path CI will use, targeting the PR branch head:

```bash
sudo -u deploy-user -H git -C /srv/app fetch origin "$BRANCH"
SHA=$(sudo -u deploy-user -H git -C /srv/app rev-parse --short "origin/$BRANCH")
# the wrapper lives IN the commit, so stage just those paths first
sudo -u deploy-user -H git -C /srv/app checkout "origin/$BRANCH" -- ops/deploy.bash ops/deploy_wrapper.bash
sudo -u deploy-user -n /bin/bash /srv/app/ops/deploy_wrapper.bash "$SHA"
```

Wrap it in a harness that prints state BEFORE and AFTER (service status, HEAD,
worktree cleanliness, the marker file, and the safety flags that must not
change). Safe to do on a host whose production workload is deliberately disabled.

**Note the bootstrap ordering:** the wrapper cannot fetch itself. The scripts
arrive with the commit, so the first CI deploy after adding them requires them
to already be on `main`.

---

## Guards must be verified by NEGATIVE CONTROL

A repo guardrail test asserted a hardcoded path:

```python
assert "bash ~/oldhost/ops/update_prod_wrapper.bash" in workflow_body
```

A legitimate host migration then failed a guard that was still satisfied in
substance. **A guard that breaks on legitimate change teaches people to edit the
guard — which is how real protection gets deleted.** Assert the INVARIANT:

```python
lines = [l for l in body.splitlines()
         if "wrapper.bash" in l and not l.lstrip().startswith("#")]
assert lines, "no deploy wrapper invoked at all"
bare = [l.strip() for l in lines if not re.match(r"\s*bash\s+", l)]
assert not bare, f"wrapper invoked without `bash`: {bare}"
```

🔴 **Then prove the new guard can FAIL.** The first rewrite here passed the real
file AND a deliberately-regressed copy — it could not fail, i.e. it was
decoration. Always run both controls:

```python
print(check(body))                      # want PASS
print(check(body.replace("bash /path/w.bash", "/path/w.bash")))  # want FAIL
```

Only the negative control catches a guard that matches nothing.

---

## Run the suite from a WRITABLE clone

A test suite that writes fixtures into its own tree (throwaway keys, temp
artifacts) cannot run inside a read-only production checkout — it dies at
conftest import with `PermissionError`. That is the ownership separation working
correctly, not a bug. Clone to a work directory and run there.

Cloning from the prod tree also needs the `safe.directory` entries above.

---

## Host-hardcoded paths in shared tooling

Any operator script carrying an absolute path from the old host breaks silently
on the new one. Probe instead:

```bash
SOURCE=""
for c in "${APP_SOURCE_REPO:-}" "$HOME/app/control" "/srv/app"; do
    [ -n "$c" ] && [ -d "$c/.git" ] && { SOURCE="$c"; break; }
done
```

Also check **guard ordering**: the check that protects uncommitted work (an
existing destination directory) must run BEFORE the environment check (missing
source repo), or a user who typo'd a real name hears the wrong error.

---

## 🔴 Merging the deploy PR fires a deploy AT THE OLD HOST

The most dangerous moment of a host migration is the merge itself. **The deploy
target is a repo SECRET, not part of the PR** — so merging a PR that contains the
new pipeline triggers a deploy run using the _old_ value.

On the one occasion cutover, the squash-merge immediately queued a deploy against
`DEPLOY_HOST` = the co-tenant host — the host that had just been deliberately fenced. It was
caught while still `queued` and cancelled with seconds of margin:

```bash
gh run list --workflow=deploy.yml --limit 3 \
    --json databaseId,status,conclusion,headSha,createdAt
gh run cancel <id>
```

**Sequence so it cannot happen:** check for a deploy-on-merge trigger BEFORE
merging → merge → immediately list and cancel any queued run → repoint the
secret → only then dispatch deliberately. Better still, flip the secret before
merging when the new host is already built.

### The CI SSH key is per-host

Repointing `DEPLOY_HOST` is not enough — the Actions key must already be
authorized on the target or every deploy dies at connect. Fingerprint both sides
and compare before the first run:

```bash
while read -r l; do [ -z "$l" ] && continue; echo "$l" > /tmp/k.pub
    ssh-keygen -lf /tmp/k.pub; done < ~/.ssh/authorized_keys
```

### Run the deploy AS the user that owns the tree

With the edit-plane / run-plane split, the workflow's SSH user cannot mutate
production — and **even `git fetch` writes inside `.git`**:

```
Process exited with status 255
error: cannot open '.git/FETCH_HEAD': Permission denied
```

Fix by invoking as the owner through the narrow sudoers rule
(`sudo -n -u <owner> /bin/bash <wrapper> <sha>`), never by loosening ownership —
the separation is the feature. Prove it by running the exact command the workflow
issues, on the host, before merging.

**Corollary — a guard can be right in spirit and too literal in practice.** The
guard above requires the wrapper line to _start with_ `bash`; adding the sudo
prefix broke it. The real invariant is "the wrapper is executed BY a bash
interpreter", so match `(\S*/)?bash\s+\S*wrapper\.bash` anywhere on the line —
then re-run the negative control to prove it still fails when `bash` is genuinely
absent.

---

## Pitfalls

- **Merging the deploy PR while `DEPLOY_HOST` still points at the old box.**
  Cancel the queued run, repoint the secret, then dispatch.
- **Assuming the CI SSH key exists on the new host.** It is per-host.
- **A read-only-looking operation that still writes** (`git fetch` →
  `.git/FETCH_HEAD`) failing under the tree-owner split.
- **`set -o pipefail` + a command whose non-match is exit 1** (`pgrep`, `grep`).
  Wrap in `{ cmd || true; }`.
- **`[ cond ] && cmd` at the end of a block** under `set -e`. Use `if/then`.
- **`pgrep -fc... || echo 0`** produces `"0\n0"`. Count lines.
- **`source venv/bin/activate` in a deploy.** Pass `--python` explicitly and
  `unset VIRTUAL_ENV`.
- **A dependency-install branch that can match nothing.** Terminal `else` that
  exits non-zero.
- **Production interpreter inside a `0750` home directory.**
- **sudo stripping `XDG_RUNTIME_DIR`.** Needs `SETENV:` in the sudoers rule.
- **`git` ownership check** misreported as a permissions or auth problem.
- **A guard asserting a literal path** rather than the invariant — and never
  proven able to fail.
- **Declaring a deploy verified from `bash -n` and a code read.** Run it.
