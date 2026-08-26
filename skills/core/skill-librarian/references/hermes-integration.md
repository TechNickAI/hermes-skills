# Hermes integration

Everything Hermes-specific lives here so the core skill stays portable. On any
other runtime, skip this file — the checks it describes report as `skipped`,
never as passing.

## Live index — ask the runtime, never infer from disk

The single most important check. A config parse tells you what _should_ load; only
the runtime tells you what _did_.

```python
import os, sys
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))
from agent.skill_commands import get_skill_commands
live = {k.lstrip("/") for k in get_skill_commands()}   # dict keyed "/name"
```

Run it with `HERMES_HOME=<profile-dir>` set, using the runtime's own interpreter
(`~/.hermes/hermes-agent/venv/bin/python`). The system Python is a different
version and will not import the agent package.

`get_skill_commands()` returns a **dict**; each value carries `skill_md_path`,
which is how you prove _which copy_ won a name collision.

**Verify both directions.** Every enabled skill present, every disabled skill
absent. A one-directional check passes vacuously.

## Profile addressing

- The default/root profile is `$HERMES_HOME` itself, **not** `profiles/*`.
- Named profiles live at `~/.hermes/profiles/<name>/`.
- **The `-p <profile>` flag is required.** `HERMES_PROFILE` as an env var is
  silently ignored — the CLI keeps using the calling profile while reporting
  success for the named one. Silent _and_ destructive for per-agent automation.
- Have the run print the absolute path it resolved, rather than trusting the
  invocation.

## Skill resolution rules

- Layout is `skills/<category>/<name>/SKILL.md`. The category directory is **not**
  the skill directory — third-party linters get this wrong.
- A profile copy **overrides** a bundled copy of the same name. Intended, not a
  collision.
- Bundled skills are **opt-in**; their absence from the index is normal.
- `platforms: [linux]` on a macOS host means correctly filtered, not missing.
- Two directories declaring the same `name:` can resolve to **neither**, and the
  skill vanishes with no error. `.archive/` dirs are the usual culprit because
  they keep a full SKILL.md with the original name.
- Duplicate `name:` values can make **both** copies disappear. Sweep `.archive/`
  for collisions.

## Configuration

`skills.disabled` in the profile's `config.yaml` is a list of names.

- Read the profile's own file directly. A bare CLI call resolves to the **host
  default profile**, so you will audit the wrong agent and not notice.
- `hermes config set` serializes a list as a quoted JSON string, which silently
  disables nothing. Write YAML directly and verify by reading it back through a
  real consumer.
- A disabled name absent from the profile tree is often a **deliberate deny
  rule** for a bundled or optional skill. Check `hermes-agent/skills/` and
  `hermes-agent/optional-skills/` before calling it dead. Verified: 4 of 4
  suspected dead entries were real deny rules.

## The bundled curator — related but different

Hermes ships `hermes curator` (an auxiliary-model background task). It handles
staleness and archiving; this skill handles correctness, ambiguity, and fit.
They complement each other.

**Critical semantics, verified One case:**

- Curator **`stale` is a label only** and does _not_ remove a skill from the
  prompt. On one agent, 26 of 69 stale skills were still fully live. Only
  **`archive`** (which moves the directory into `skills/.archive/`) excludes.
- **Never read a stale count as context savings.** Curator state and
  `skills.disabled` are independent mechanisms.
- `hermes curator usage --json` is the best inventory source: per-skill `state`,
  `provenance` (`built-in` / `hub` / `agent`), `use_count`, `view_count`,
  `pinned`, and timestamps.
- `consolidate` defaults to **off**, so its LLM merge pass never runs. Do not
  enable it before an audit — an unsupervised body merge can destroy content that
  is ahead of its counterpart.
- Skills without a `version:` field are invisible to its staleness checks.
- Use `pin` to protect safety and recovery skills before any pruning pass.

## Provenance decides write permission

From `hermes curator usage --json`:

| provenance | meaning                       | editable in place?      |
| ---------- | ----------------------------- | ----------------------- |
| `agent`    | created locally by this agent | yes                     |
| `built-in` | ships with Hermes             | no — upgrades overwrite |
| `hub`      | installed from a tapped repo  | no — fix upstream       |

Do not infer provenance from the path alone.

## Taps — discovery only

```bash
hermes skills tap list
hermes skills tap add <owner>/<repo> --path skills/<pack>/
```

- **Tapping costs nothing.** No loader reads `taps.json`; only `install` writes
  skills to disk. Tap broadly, install narrowly.
- Tap identity is `(repo, path)`, so one repo can supply several packs. Older
  builds dedupe on repo alone and silently keep only the first — if you added two
  packs and `tap list` shows one row, that build predates the fix.
- Bare `hermes skills search` skips custom taps; use `--source github`.
- A bare ambiguous `hermes skills install <name>` can print a disambiguation
  table and **exit 0 without installing**. Verify SKILL.md landed on disk; never
  trust the exit code.

## Upgrade handling — the new-skill problem

When Hermes ships new bundled skills, they arrive untriaged. On each run:

1. Diff the current bundled set against the set recorded in
   `.skill-librarian.md`.
2. For each new arrival, apply the same judgement as any other skill: does it
   duplicate something, does it shadow an existing description, does it fit this
   agent's role?
3. Record the decision so the next run does not re-litigate it.

This is the gap the curator does not cover: it manages what is already there,
not what just showed up.

## Usage telemetry

`use_count` and `view_count` come from `hermes curator usage --json`. Deeper
history lives in the profile's `state.db`.

- Open read-only: `file:{db}?mode=ro`.
- Per-profile stores differ — a named profile uses
  `$HERMES_HOME/state.db`, the root profile uses `~/.hermes/state.db`.
- **Never prune rows where `role='tool'`**; they pair with assistant tool calls.
- Count real `skill_view` calls, not name mentions in prose.
- A thin history cannot support a "never used" claim. Check the window length
  before drawing conclusions.

## Gateway safety

- **Never reload your own gateway mid-turn**, and never self-invoke
  `hermes gateway restart` — the command is killed by the process it restarts.
- Prove a reload by **PID change**, not by exit code or `is-active`.
- launchd domains differ per host (`gui/501` vs `user/501`); systemd user units
  on Linux.
