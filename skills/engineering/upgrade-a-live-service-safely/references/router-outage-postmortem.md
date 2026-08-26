# Case study: the router fleet-router outage, 2026-07-26

> **Resolution (same session): builds moved off the router entirely.**
> `.github/workflows/build-standalone-artifact.yml` on the fork builds on a free
> GitHub `ubuntu-24.04-arm` runner (the repo is PUBLIC, so arm64 minutes are
> free). Verified end-to-end: build 10m38s, artifact 586 MB (4.7 GB unpacked),
> downloaded to the router, unpacked to `releases/<name>/`, smoke-tested on port
> 20129 against a `sqlite3 .backup` copy of the DB — healthy in 8s, `/v1/models`
> 200, live `MainPID=3060` unchanged across three consecutive runs, script exit 0.
> Nothing was swapped; cutover remained a human decision.
>
> Generic, reusable form of this: `references/ci-offload-build-and-stage.md`,
> `templates/ci-standalone-build.yml`, `scripts/stage_and_smoke.sh`.
>
> **Right-sizing follow-on:** router runtime RSS is 1.11 GB, systemd all-time
> `MemoryPeak` 1.18 GB, worst whole-system runtime day 3.86 GB — only the build
> ever needed 15 GB. With builds in CI, `c8g.large` (2 vCPU/8 GB, $63.48/mo)
> replaces `r8g.large` ($94.20/mo): ~$31/mo, ~$369/yr, still 2× headroom.
> Note there is no "burstable RAM" in EC2 — T-family bursts CPU only.

A worked example of every failure mode in this skill, plus the client-side retry
semantics that determine how much a router outage actually hurts. Companion to
the manually-authored `the router` skill (which cannot be edited by curation —
put the router learnings here and cross-reference).

## Setup

- Host: `<router-host>` → `<router-host-ip>` → EC2 `<instance-id>`,
  **r8g.large** (non-burstable Graviton, 2 vCPU), ca-central-1, tag `the router`.
  **There is no `the router.<internal-domain>`** — it does not resolve. `dig +short`
  before acting when a domain is spelled differently.
- Supervision: `~/.config/systemd/user/the router.service`
  ```
  WorkingDirectory=/home/ubuntu/src/the router/.build/next/standalone
  ExecStart=/usr/bin/node dev/run-standalone.mjs
  EnvironmentFile=/home/ubuntu/src/the router/.env
  Restart=on-failure
  ```
  It IS supervised — but by the **user** manager. `systemctl is-active the router`
  at system level returns `inactive`, which produced a false "no supervisor,
  nothing will restart it" alarm. The `ps -o ppid` giveaway: parent is
  `/usr/lib/systemd/systemd --user`.
- Goal: rebase the fork onto `upstream/release/v3.8.49`.

## The code work succeeded

Worth separating from the deploy failure: the upgrade itself was fine.

- Cherry-picked the single fork commit (`<NEW_FLAG>`) onto the release
  branch; conflicts in `anthropicHeaders.ts` and `base.ts`.
- Upstream had **absorbed most of the patch** — it now centralises wire constants
  in `src/shared/constants/claudeCodeClient.ts` and already exports
  `ClaudeCodeEntrypoint` and `getClaudeCodeUserAgent(entrypoint)`. The fork patch
  therefore **shrank** to just the env-var reader. Always check whether upstream
  evolved an equivalent before force-keeping your side of a conflict.
- **Near-miss worth remembering:** the old fork hardcoded `cch=00000` and a
  hand-rolled `buildHashFor(...)`. Resolving toward "keep ours" would have
  hardcoded a stale `cch` value — but upstream's `cch=00000` is a **placeholder
  that `signRequestBody()` replaces at runtime** with an xxHash64 integrity
  token. Keeping the fork's literal would have broken request signing silently.
  An over-strict post-resolve assertion is what surfaced it. Write asserts that
  can fail; a failing assert that turns out to be _your_ bug is the point.
- Result: exactly one commit on top of upstream, 5-line diff, 5/5 fork tests
  green.

## The deploy failure

`npm run build:release` begins with **`rm -rf .build dist`** — deleting the
systemd unit's `WorkingDirectory` while the service ran from it. The live process
survived on memory-mapped code, so health checks stayed green (0.5s responses)
and the rollback window closed silently.

Then the Turbopack compile saturated both vCPUs, starving the Node process (HTTP
stopped answering) and sshd (box unreachable). **~30 minutes of full-fleet
downtime.**

Compounding error: the first build ran as `ssh host 'npm run build:release'`.
When the box got starved the SSH pipe dropped and killed the build mid-write,
leaving `.build` as a **1.4M fragment** (from 808M).

### Diagnosis I got wrong on the record

I called it CPU-credit exhaustion on a t4g.medium. It is an **r8g.large — no CPU
credit mechanic exists on it.** Plain 2-core saturation was sufficient. The
skill's existing `aws-ec2-deployment.md` reference warns about credit burn on
_burstable_ t4g instances for _Docker_ builds; that is a different failure and I
pattern-matched onto it. Check `InstanceType` before invoking credits.

## Recovery that worked

1. TCP-probe :443 and :22 from outside → both OPEN but HTTP hanging ⇒ starved
   process, not dead host.
2. `aws ec2 reboot-instances --instance-ids <instance-id> --region ca-central-1`
   (**plural**; `reboot-instance` is invalid and dumps the whole subcommand list).
3. Recovery ladder observed: `000` → `502` (Caddy up, Node booting) → `200` at
   ~2 min.
4. Restore:
   ```bash
   cd ~/src/the router
   rm -rf .build && tar xzf ~/rollback-build-20260726T220501Z.tar.gz   # 808M back
   git checkout main
   systemctl --user restart the router.service
   ```
5. Verified: `NRestarts=0`, port listening in <3s, real routed inference
   (`cheap → gpt-5.6-luna → "ok"`), all 7 combos intact, settings preserved
   (`codexSessionAffinityTtlMs=3600000`, `stickyRoundRobinLimit=50`, `cheap`
   still `round-robin`), fork patch present in the running bundle (49 files
   reference `cc_entrypoint`), and fleet traffic resumed across all 9 members.

## Correct approach for the retry (the operator's call)

Build **into a separate release directory** and switch over atomically when done
— not in place. Combine with a build host that shares OS+arch but isn't serving:

- Build host candidate: **Hex** — Linux aarch64, 4 vCPU, node v24.14, not in the
  router's serving path. Matches the router's `Linux aarch64` / node v24.18.
  (Watch: node minor differs; Hex was at 80% disk with ~20G free.)
- **This Mac cannot be the build host.** Darwin arm64 ≠ Linux aarch64. The bundle
  carries **37 native `.node` binaries**; `better-sqlite3` compiles per-platform
  and `sharp` only installs `sharp-linux-arm64` on Linux. A macOS build produces
  Darwin binaries that fail to import on the router.

## How Hermes clients retry the router

Read from the installed package at
`~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/`.

**SDK retries are deliberately disabled.** `agent/anthropic_adapter.py` sets
`max_retries: 0` on every client, with the in-code rationale: the SDK default of 2
_ignores `Retry-After`_ and double-retries inside Hermes' own loop, "burning
request slots against a bucket that won't refill for minutes" (#26293). Do not
"fix" this by re-enabling SDK retries.

**Policy lives in the outer loop** (`agent/conversation_loop.py`):

| failure class                    | behavior                                                             |
| -------------------------------- | -------------------------------------------------------------------- |
| 429 / billing / quota            | **immediate fallback, no retry** — primary won't recover in-window   |
| timeout / overloaded (503, 529)  | **1 retry, then fall back**                                          |
| 500 / 502                        | transient, retried                                                   |
| transport blip (auxiliary calls) | `auxiliary.transient_retries`, default 2 → 3 attempts, clamped [0,6] |

Failed providers get marked unhealthy and **skipped for 600s**
(`_AUX_UNHEALTHY_TTL_SECONDS`, `auxiliary_client.py`) rather than hammered.

### Resilience gap found while auditing

A member's `fallback_providers` first rung was `custom:the router → fallback` —
**the same host that just died**, therefore useless during a router outage. Only
the later `openrouter → @preset/hermes-fallback` rung was a real escape hatch.
When auditing outage resilience fleet-wide, confirm at least one rung leaves
the router entirely.

### Reading a member's router key

Members use `key_env: APP_KEY` with the value in `~/.hermes/.env`, NOT
inline in `config.yaml`. Grepping `config.yaml` for `api_key:` grabs an unrelated
provider key and returns a confusing **401 AUTH_002** against the router:

```bash
grep -hE '^APP_KEY=' ~/.hermes/.env | cut -d= -f2- | tr -d '"' | tr -d "'"
```

Also: complex `curl`/`grep` one-liners inlined through `ssh host '...'` break on
quote nesting. `write_file` a small `.sh`, `scp` it, run it, delete it.

## Verifying a member is healthy (vs merely idle)

"Last call was N minutes ago" is not evidence of breakage. Prove it end-to-end
from THEIR box, THEIR key, THEIR default combo — a member showed no traffic for
50 minutes and was simply idle; her gateway (launchd `ai.hermes.gateway`) had an
`ELAPSED` of 5 days, proving it rode through the outage without crashing. A long
uptime on the gateway process is strong evidence the client side never broke.
