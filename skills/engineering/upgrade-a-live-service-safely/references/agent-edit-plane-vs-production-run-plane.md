# Agent edit plane vs production run plane

Use this when autonomous agents can modify the same product that is currently running. The core safety property is architectural: **the identity and filesystem where an agent edits must not be able to mutate the live tree or its persistent state.** Prompts, Git conventions, command regexes, and tool-level path guards are useful secondary controls, not containment.

> ## ⚠️ the operator rejects releases+symlink — offer single-directory + deploy lock
>
> **one occasion, a trading agent rebuild.** the operator, unprompted: _"I don't agree with the
> releases directory and assembly link. I've always just run a Git pull to
> update the working directory or use Docker, but I think the releases thing is
> overkill and just winds up piling up shit. I don't need an atomic rollback,
> so let's just do one directory."_
>
> **Do not open with the releases/`current` topology on the operator's hosts.** He has
> ruled on it. The identity separation below is the load-bearing part and he did
> NOT object to it — keep that. Swap only the release mechanism.
>
> **The real hazard releases were solving, which still needs an answer.** a trading agent
> is mostly cron, and cron re-reads scripts from disk every tick. `git pull` is
> not atomic — it writes files over several seconds, so a tick firing mid-pull
> can execute a half-updated codebase **while performing irreversible actions**. Name this
> risk explicitly rather than silently accepting it; it is why the original
> `update_prod.bash` was written that way.
>
> **Single-directory pattern that keeps the safety and drops the pileup:**
>
> ```text
> /srv/app/app/            # THE one directory. git reset --hard <sha>.
> /srv/app/shared/         # state, logs — separate EBS volume
> /run/app/deploy.lock     # held for the duration of the update
> ```
>
> - Deploy: take lock → `git fetch && git reset --hard <sha>` → install deps →
>   verify → release lock → restart services.
> - Every cron entrypoint takes a **shared read** on that lock at start. A pull
>   is 2–3 s and ticks are minutes apart, so nothing waits in practice.
> - Use `git reset --hard <sha>`, **not `git pull`** — deterministic tree at a
>   known SHA, no merge surprises, and `git rev-parse HEAD` becomes a truthful
>   deployed-SHA probe (preserving the truth chain below).
> - Rollback is `git reset --hard <old-sha>` — the same operation as deploying,
>   which is why the absence of atomic rollback costs nothing here.
>
> 🔴 **The entrypoint lock alone is NOT sufficient — this was found in review
> and the naive version above is incomplete.** A shared lock taken _at start_
> gates new job launches; it does nothing for a job **already running**. Python
> imports lazily, so a process that started before the reset can import a module
> **after** the tree changed underneath it and execute mixed-version code on a
> live order. Two additions are required:
>
> 1. **Drain, don't just gate.** The deploy pauses the scheduler and waits for
>    in-flight jobs to finish before mutating. The lock FD must survive `exec`
>    and cover the gateway, process-manager services, and manual invocations —
>    not only cron entrypoints. A stale-lock timeout must never preempt a
>    legitimately running job.
> 2. **An interrupted `git reset --hard` leaves a MIXED TREE.** Kill, disk-full,
>    I/O error, or reboot mid-reset releases the lock and the next tick runs
>    partial files. `HEAD == requested SHA` does **not** prove the checkout
>    completed. Verify `git status --porcelain` is empty and that money-path
>    modules import in a **fresh** process; quarantine the service rather than
>    trading on an unverified tree.
>
> Docker is the other acceptable answer to the operator (he named it himself): the image
> digest is the deployed identity and there is no partial-update window at all.
> For cron-heavy Python with a venv, one directory + deploy lock is less
> machinery; containerize later if wanted.

## Where agents work vs how CI/CD deploys — draw the whole map

the operator asked for this explicitly after a first pass described the pieces but never
connected them: _"Still not clear to me where the agents work vs how CI/CD
deploys, map that out."_ **When explaining this architecture, draw the end-to-end
diagram with the identities and the trust boundaries marked.** A prose list of
components does not answer "how does an edit become production".

The load-bearing move is **two machines**: agent work does not happen on the
production box at all.

> ⚠️ **the operator overrode the two-machine split on one occasion.** _"I don't want a
> whole nother machine for editing. the owner will edit with a trading agent, and it needs to
> be in a local directory. the owner is interacting with prod. The separation I'm
> looking for is not permissioning, its just giving the owner a place to edit that
> is separate from prod, and a deploy process that goes through CI Testing and
> PR reviews (with bug bots). We can have a second user on the same machine,
> that owns the deploy directories."_
>
> **Offer the one-machine / two-user shape first on his hosts.** Same box:
> the agent edits under `~/agent-work/<task>/` as the normal login user, prod
> lives at `/srv/app/app/` owned by a separate `app-deploy` user, and the login
> user has **read but not write** on the prod tree. That single boundary
> prevents the incident that actually happened (a peer agent under the same user
> deleting the prod tree) without the permission complexity he rejected.
>
> When an operator declines containment, **do not silently drop the risk — state
> the honest residual once, plainly, and move on.** The version that landed
> well: _"Because the agent writes and runs code in the same OS-user, IAM, and
> network context as the live daemon, a hallucinated script or prompt-injected
> payload can execute live trades, drop the database, or read the keys. CI and
> PR review govern what reaches prod; they do nothing during drafting. The
> separate deploy user prevents the specific incident that happened. That's the
> boundary being bought, and it's narrower than 'the agent is contained'."_
> Record it as an accepted tradeoff, do not re-litigate it in later turns.

The two-machine version below remains correct where an operator wants full
separation:

```text
┌─ DEV BOX (separate small instance, or the operator's Mac) ─┐
│  user: app-agent                                           │
│  /var/lib/app-agent/workspaces/<task-id>-<rand>/           │
│     one full independent clone + one branch per task        │
│  Agent edits, runs tests, opens PRs HERE.                   │
│  NO exchange/prod keys. NO prod DB. NO ssh key to prod.     │
└─────────────────────────────────────────────────────────────┘
                    │  git push + gh pr create
                    ▼
┌─ GITHUB ────────────────────────────────────────────────────┐
│  PR → required checks → merge queue → main                  │
│  → deploy workflow fires on push to main                    │
└─────────────────────────────────────────────────────────────┘
                    │  OIDC → assume deploy role
                    │  SSM Run Command (no SSH key in CI)
                    ▼
┌─ PROD BOX ──────────────────────────────────────────────────┐
│  user: app-prod    runs code, CANNOT write it               │
│  user: app-deploy  writes code, CANNOT trade                │
│  /srv/app/app/     ← git reset --hard <sha>                 │
│  /srv/app/shared/  ← state + logs (separate volume)         │
│  /run/secrets/     ← tmpfs, fetched from SSM at boot        │
└─────────────────────────────────────────────────────────────┘
```

Three rules make it hold:

1. **The agent never touches prod.** No SSH credential exists from the dev box
   to the prod box. This is not policy; it is the absence of a key.
2. **CI deploys, not the agent.** GitHub Actions authenticates by OIDC (no
   long-lived AWS key), assumes a narrow deploy role, and invokes ONE root-owned
   script through SSM Run Command: `/usr/local/bin/app-deploy <sha>`. No
   arbitrary arguments, no shell-into-prod step to abuse.
3. **"Deployed" is verified, never asserted.** Deploy succeeds only when
   `git rev-parse HEAD` == merged SHA == the SHA the running process reports.
   An hourly drift check compares live SHA against `origin/main` and alerts when
   they diverge or a green PR ages past its SLA.

Rule 3 is the direct fix for an agent believing its code is live: it cannot
assert deployment, it must read it from the running system, and an unmerged PR
makes the drift check say so out loud.

> ⚠️ **Right-size rule 3 to the team.** A contrarian review lane cut the merge
> queue + hourly-drift-SLA machinery on the a trading agent rebuild and it was the
> correct call: the operator merges PRs by hand and the pipeline demonstrably
> worked (40 merges in 14 days, 1 closed-unmerged in 30). _"Platform engineering
> for a team that is not this team."_ **A daily "is HEAD what we think" check is
> enough for a solo operator.** Keep the truth chain (deploy records the SHA,
> the process reports it, verify all three match) — that part is cheap and is
> what actually fixes "the agent thought it was live". Drop the queue, the SLA
> alerting, and the hourly cadence unless a team is actually merging.
>
> Also: **a drift check that reads the worktree SHA can report healthy while
> long-lived processes still execute the old code.** Expose the loaded SHA from
> each live PROCESS (plus PID start time and config hash), not just
> `git rev-parse HEAD` in the directory.

**Human/admin access is a separate question from agent access — ask it.** On the
a trading agent rebuild the operator specified: the co-tenant agent (Hex) gets no access at all
initially ("I may give it later if it needs it"), while the operating agent
(the operations agent) keeps SSH "because you need to fix it". Do not assume a co-tenant keeps
access after a split, and do not lock yourself out in the name of hardening.

## Reference topology (releases variant — use only where the operator wants it)

```text
/srv/app/
  control/                       # deploy identity only
  releases/<timestamp>-<sha>/    # immutable after build
  current -> releases/...        # deploy identity alone may flip
  shared/{env,state,logs}/        # narrowly writable runtime state
/var/lib/app-agent/workspaces/
  <task-id>-<random>/             # independent full clone per task
```

Use three Unix identities:

- **agent:** owns task clones; cannot traverse or write `/srv/app`; has no production secrets, systemd control, or production Docker socket.
- **runtime:** reads `current`; can write only the required paths under `shared/`; cannot modify releases or deploy.
- **deploy:** creates a release from a merged SHA, links shared paths, runs smoke checks, atomically flips `current`, and restarts/drains the service. Expose only a fixed, root-owned deploy command or CI path—not arbitrary sudo arguments.

Make release code root/deploy-owned and read-only after staging. Keep SQLite backups and snapshots outside every agent-writable tree. If an agent sandbox needs Docker, do not mount the host Docker socket or production paths.

## Concurrent coding tasks: independent clones are a valid baseline

When shared Git metadata is unacceptable, allocate one full clone per task. Accelerate without coupling writable state by cloning from a read-only local bare mirror (`git clone --reference-if-able...`), while retaining an independent `.git`, index, refs, branch, dependency cache namespace, ports, volumes, and test database.

Workspace manager requirements:

1. Allocate `workspaces/<task-id>-<random>`; never derive a scratch path by deleting/reusing an arbitrary requested destination.
2. Record task, branch, PID/container, creation time, remote and PR number in metadata outside the clone.
3. Run one container or microVM per clone for unattended work; set CPU, memory, PID and disk quotas plus explicit egress.
4. Push a branch/PR as the handoff. Production never runs from a workspace.
5. GC only after confirming no live PID/container and that work is pushed, merged, or explicitly abandoned. Bound both idle time and maximum age.

This mirrors cloud coding-agent practice: isolated VM/container, private clone, branch, PR. It also avoids races on a shared `.git/index` or refs.

## Promotion and deployment truth

The only path to production should be:

```text
agent clone -> branch -> PR -> required CI/review -> merge queue -> main SHA
-> release/image build -> smoke -> activate -> record deployed SHA
```

Before activation, write an immutable `DEPLOYED_SHA` (and ideally artifact digest/build timestamp) into the release. After activation, verify all of:

- `readlink -f current` identifies the expected release;
- `current/DEPLOYED_SHA` equals the merged main SHA;
- the live process reports that same SHA through `/version`, status output, or an equivalent runtime probe;
- GitHub's production Deployment records that SHA and is marked success only after the live probe;
- systemd is healthy, restart count is stable, and the process cwd/executable resolves to the activated release.

A PR existing, CI passing, or an agent saying "done/live" is not deployment evidence. Alert on two separate classes:

- **Unmerged-work drift:** agent-created PR remains draft/open/conflicted/out-of-date beyond an SLA.
- **Deployment drift:** live SHA, `current` manifest, latest successful production Deployment SHA, and intended `origin/main` SHA differ.

Teach agents to answer "is this live?" by querying this truth chain, never by inspecting their workspace branch.

## Process-manager choice

- **Single Linux host:** systemd is the default. Use explicit user, working directory, environment file, restart policy, stop timeout, filesystem hardening and resource limits.
- **Compose:** appropriate when the deployable artifact is an immutable image; mount state/config separately and deploy by digest, not a mutable tag.
- **Kubernetes/GitOps:** useful when scheduling, multi-tenancy, reconciliation or fleet scale justify it; usually unnecessary for one stateful agent host.
- **PM2:** workable for Node gateways, but adds little where systemd already owns boot, cgroups, journald and service permissions.
- **Blue-green:** valuable only if the singleton/state model permits two simultaneous instances. For stateful agent gateways, stage + health-check + atomic symlink flip + controlled restart is usually simpler.

## Hermes-specific guardrail interpretation

Hermes file-tool write guards/denylists reduce accidental writes by file tools, but shell/terminal authority remains the OS user's authority. Dangerous-command classifiers are also footgun guards, not an RCE or filesystem containment boundary. Prefer a Docker/remote terminal backend or OS-level separation, and verify exact installed-version support before relying on a named config feature.

**Correction (one occasion):** an earlier version of this file, following a research
lane, said not to infer that `lifecycle_guard` exists. That was wrong in the
literal direction — **`cron/lifecycle_guard.py` DOES exist in Hermes source**
(it has blocked terminal commands on this fleet many times, and has its own
crash modes). It is _undocumented_, not absent. A research lane finding no public
docs for an identifier proves absence of documentation, never absence of the
feature; check the installed source before concluding either way.

The substantive conclusion is unchanged and is what matters: lifecycle_guard and
the file-tool denylists gate `write_file`/`patch` and pattern-match command text.
They do **not** contain `terminal`, which runs with the full authority of the OS
user. **No Hermes-layer setting would have prevented the `rm -rf` that destroyed
the a trading agent production tree.** State that plainly when an operator asks whether a
config flag can protect production — the honest answer is that the boundary must
be Unix permissions or a container.

## Research evidence hierarchy for deployment-pattern questions

Separate "supported topology" from "observed production practice":

1. Official docs/source prove supported service managers, sandbox knobs and lifecycle semantics.
2. Named operator reports or customer writeups prove actual production use.
3. Comparable agent platforms establish convergent patterns (per-task VM/container + clone + branch/PR).
4. Practitioner communities are supporting signal; label weak or absent classes instead of padding with generic posts.

Do not present SEO deployment guides as first-party evidence, and do not equate a Helm chart, PM2 snippet or advertised feature with adoption. If a requested source class yields no claim-grade result, say so explicitly.
