# hermes-skills

A library of **22 skills** for [Hermes](https://github.com/NousResearch/hermes-agent)
agents, grouped into role packs so an agent installs what its job needs and
nothing else.

## What a skill is

A skill is a folder holding a `SKILL.md` — a written procedure the agent loads on
demand, plus any scripts and templates it needs. Think of it as an expert
coworker's notes: the exact commands, the order to run them in, the things that
look right but silently fail.

The agent sees only each skill's name and one-line trigger by default. When a
task matches, it opens the full skill and follows it. So a good skill turns "the
model improvises" into "the model executes a procedure that already worked."

Every skill here was written from real runs, not from imagination. They include
the dead ends, because knowing what does not work saves the next agent the same
hour.

## Why packs instead of one big pile

Every installed skill costs context. Its name and description sit in the system
prompt on **every single turn**, and the model reads that list before it reads
your actual request.

Measured on a real 11-agent fleet: an agent carrying 281 skills spends ~6,250
tokens on the index before it reads a word of the task. One agent had never once
loaded **55%** of what it was carrying.

The token cost is survivable. The attention cost is the real problem — a model
choosing from 281 descriptions chooses worse than one choosing from 90. So skills
are grouped by the role that needs them, and an agent taps only its packs.

## Quick start

```bash
# Tap the packs this agent needs (tapping = discoverable, costs nothing)
hermes skills tap add TechNickAI/hermes-skills --path skills/core/
hermes skills tap add TechNickAI/hermes-skills --path skills/engineering/

hermes skills search review        # search your tapped packs
hermes skills install multi-review # copy into ~/.hermes/skills/ and activate
```

Tapping makes a skill **discoverable**; installing puts it in the agent's index
and costs context. That split is deliberate — tap broadly, install narrowly.

Not running Hermes? Every skill is plain markdown. Copy the folder into whatever
your agent reads and it works.

> **Multiple packs from one repo** needs a Hermes build with `(repo, path)` tap
> identity. Older builds dedupe on repo alone and silently keep only your first
> tap. Check with `hermes skills tap list`: if you added two packs and see one
> row, your build predates that fix.

## The catalog

### `core` — every agent, whatever its job

| Skill              | What it does                                                                               | Needs                |
| ------------------ | ------------------------------------------------------------------------------------------ | -------------------- |
| `deep-dive`        | Research a question across every relevant source and come back with a decision, not links  | —                    |
| `multi-review`     | Review any artifact through a panel of diverse lenses across model families, then converge | —                    |
| `moa-solve`        | Throw several models at one hard problem and synthesize the best answer out of the spread  | —                    |
| `mob-check`        | What real people are actually saying right now — Reddit, X, HN, YouTube — ranked, not SEO  | —                    |
| `grok-search`      | Real-time web and X search via xAI's Grok, for when general web search misses              | `XAI_API_KEY`        |
| `recall`           | Rebuild context from prior sessions, memories, and transcripts after `/new`                | —                    |
| `memory-cleanup`   | Shrink a bloated `MEMORY.md` without losing facts — compress, relocate, offload            | —                    |
| `project-steward`  | Run a portfolio of long-running projects like a chief of staff instead of a task runner    | `TELEGRAM_BOT_TOKEN` |
| `trust-framework`  | Govern your own autonomy: act vs. ask, one-way vs. two-way doors, earn freedom over time   | —                    |
| `robustify-doctor` | Is this agent actually healthy? Collects facts across twelve subsystems, then reads them   | Python 3.9+          |
| `keep-going`       | `/keep_going` — re-anchor an agent that asked a question instead of doing the work         | —                    |
| `report`           | File a bug or piece of feedback from any session, routed for triage                        | —                    |

### `engineering` — agents that write and ship code

| Skill                 | What it does                                                                              | Needs                 |
| --------------------- | ----------------------------------------------------------------------------------------- | --------------------- |
| `address-pr-comments` | Triage bot and human PR feedback, fix what's valid, push back on what isn't, reply to all | `gh` CLI              |
| `pr-review-sweep`     | Nightly sweep of merged PRs for review comments nobody handled                            | `gh` CLI              |
| `diagram-rendering`   | D2, Mermaid, Graphviz, and Chart.js text into a chat-ready PNG, with the render gotchas   | chromium, network     |
| `mini-app`            | Operate the Caddy + PM2 + Tailscale app-router that serves small apps at clean URLs       | Caddy, PM2, Tailscale |

### `productivity` — documents, comms, scheduling

| Skill                  | What it does                                                                            | Needs              |
| ---------------------- | --------------------------------------------------------------------------------------- | ------------------ |
| `email-steward`        | Scheduled inbox triage: kill debris, quarantine promos, surface only what needs a human | `gog`/`himalaya`   |
| `google-docs`          | Create, format, edit, export, and quality-check Google Docs from markdown               | `gog` CLI          |
| `google-sheets`        | Build and verify Sheets from CSV, JSON, or computed tables                              | `gog` CLI, python3 |
| `google-slides`        | Markdown to a real Slides deck, with a visual QA pass                                   | `gog` CLI, pandoc  |
| `imessage-bluebubbles` | Send, read, and search iMessage from an agent on macOS via the BlueBubbles bridge       | macOS, BlueBubbles |
| `vapi-calls`           | Place real outbound phone calls — reminders, confirmations, booking an appointment      | `VAPI_API_KEY`     |

`skills/MANIFEST.yaml` is the machine-readable version of this table, generated
and CI-verified. A skill lives in exactly one pack; if two packs both seem right,
it is probably two skills.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

- **Zero PII.** No real names, hostnames, tailnet addresses, private domains, or
  absolute user paths. CI enforces this.
- **Pick the pack by what the skill does**, not by who happens to use it today.
- **Bump `version:`** on every content change, or installs read your update as a
  local customization and skip it.
- **Write what you verified**, including what you tried that did not work.

## Related

- [`hermes-config`](https://github.com/TechNickAI/hermes-config) — setup: config,
  plugins, personality templates, infrastructure patterns
- `hermes-skills-private` — packs that cannot be published: environment-specific
  operations and alpha-bearing strategy

## License

MIT — see [LICENSE](LICENSE).
