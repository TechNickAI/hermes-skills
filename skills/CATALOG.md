# Skill catalog

This file is generated from each skill's metadata. Do not edit it by hand.
Use it to choose a small set of relevant skills without opening every skill file.

## Start here

Every installed skill's name and description sit in the system prompt on _every_
turn, and its body loads whenever it triggers, so a long list costs attention on
work that has nothing to do with it.
Unless the person asks for something specific, propose these three and stop:

- **`deep-dive`** — "Go figure this out" returns a recommendation instead of a
  reading list. (Claude: degraded)
- **`keep-going`** — It finishes the work instead of stopping to ask which option
  you want. (Claude: native)
- **`multi-review`** — Important drafts and decisions get reviewed from several
  angles first. (Claude: degraded)

Everything below is the full index, for when someone names a need these three do
not cover.

`Claude` values: `native` (works fully), `degraded` (runs but loses its
differentiator — say so out loud), `unsupported` (never recommend it in Claude).

## deep-dive

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when told "do a deep dive", "go figure this out", or "don't reinvent the wheel" - researches a question across every relevant source and returns a decision.
- **Use when:** told "do a deep dive", "go figure this out", or "don't reinvent the wheel" - researches a question across every relevant source and returns a decision.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Portable to Hermes and Claude Code. In Claude, map the named research tools and delegation/panel mechanisms to available equivalents; unsupported source classes are reported, not silently omitted.
- **Claude:** degraded — Full method in Claude Code using its own web, file, and subagent tools; prior-session search and cross-family synthesis are unavailable.
- **Size:** 34,360 B body, loaded when the skill triggers (~8,590 tokens); 34,360 B across 1 file(s) total
- **Path:** `skills/core/deep-dive`

## grok-search

- **Pack:** core
- **Scope:** solo
- **What it does:** On-demand real-time web and X (Twitter) search via xAI's Grok.
- **Use when:** On-demand real-time web and X (Twitter) search via xAI's Grok.
- **Prerequisites:** env: XAI_API_KEY (xAI console)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once XAI_API_KEY is available.
- **Size:** 5,499 B body, loaded when the skill triggers (~1,375 tokens); 23,112 B across 4 file(s) total
- **Path:** `skills/core/grok-search`

## keep-going

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when the user says "/keep_going", "keep going", or "continue" after the agent has stopped short — asked "which option?", narrated a plan instead of executing it, or claimed a blocker that is not real — while the user has already given clear direction.
- **Use when:** the user says "/keep_going", "keep going", or "continue" after the agent has stopped short — asked "which option?", narrated a plan instead of executing it, or claimed a blocker that is not real — while the user has already given clear direction.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Portable to Hermes, Claude Code, and similar coding agents.
- **Claude:** native — Works in Claude with no additional setup.
- **Size:** 3,453 B body, loaded when the skill triggers (~863 tokens); 3,453 B across 1 file(s) total
- **Path:** `skills/core/keep-going`

## memory-cleanup

> **Not for Claude.** Cleans Hermes MEMORY.md / USER.md / SOUL.md files, which do not exist in Claude.

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when a Hermes MEMORY.md or USER.md file is too large, bloated, stale, or over the recommended cap and you need to reduce prompt footprint without losing important facts.
- **Use when:** a Hermes MEMORY.md or USER.md file is too large, bloated, stale, or over the recommended cap and you need to reduce prompt footprint without losing important facts.
- **Prerequisites:** None
- **Works without setup:** Yes in Hermes (not available in Claude)
- **Compatibility:** Hermes-specific memory-file layout and conventions.
- **Claude:** unsupported — Cleans Hermes MEMORY.md / USER.md / SOUL.md files, which do not exist in Claude.
- **Size:** 17,524 B body, loaded when the skill triggers (~4,381 tokens); 50,529 B across 8 file(s) total
- **Path:** `skills/core/memory-cleanup`

## moa-solve

> **Not for Claude.** Requires the native Hermes MoA fan-out runtime.

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when you have a HARD, open-ended, high-stakes problem worth throwing multiple AI models at and pulling the best solution out — architecture decisions, strategy design, thorny debugging, research synthesis, "what am I missing", tool/system design.
- **Use when:** you have a HARD, open-ended, high-stakes problem worth throwing multiple AI models at and pulling the best solution out — architecture decisions, strategy design, thorny debugging, research synthesis, "what am I missing", tool/system design.
- **Prerequisites:** None
- **Works without setup:** Yes in Hermes (not available in Claude)
- **Compatibility:** Hermes-specific; requires the native MoA runtime.
- **Claude:** unsupported — Requires the native Hermes MoA fan-out runtime.
- **Size:** 19,681 B body, loaded when the skill triggers (~4,920 tokens); 41,130 B across 5 file(s) total
- **Path:** `skills/core/moa-solve`

## mob-check

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when the user wants to know what real people are actually saying about a topic right now, not the SEO/editorial version.
- **Use when:** the user wants to know what real people are actually saying about a topic right now, not the SEO/editorial version.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude with no additional setup.
- **Size:** 16,908 B body, loaded when the skill triggers (~4,227 tokens); 58,589 B across 4 file(s) total
- **Path:** `skills/core/mob-check`

## multi-review

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when reviewing almost any meaningful artifact, decision, action, plan, code change, prompt, skill, research summary, outbound message, or public-facing content.
- **Use when:** reviewing almost any meaningful artifact, decision, action, plan, code change, prompt, skill, research summary, outbound message, or public-facing content.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Portable review method. Native multi-model orchestration examples are Hermes-specific; Claude can run the method with Claude subagents but loses model-family diversity.
- **Claude:** degraded — The review method transfers, but cross-model-family diversity needs Hermes; in Claude it becomes Claude reviewing Claude.
- **Size:** 48,649 B body, loaded when the skill triggers (~12,162 tokens); 131,739 B across 17 file(s) total
- **Path:** `skills/core/multi-review`

## project-steward

> **Not for Claude.** Drives a Hermes living board and cron cadence.

- **Pack:** core
- **Scope:** solo
- **What it does:** Run a portfolio of long-running projects as a chief of staff rather than a task runner.
- **Use when:** you have several open-ended efforts that each need periodic attention, when scheduled agent runs are producing activity without progress, when a notification channel has become an unreadable wall of updates, or when you want an agent to direct specialist agents instead of doing their work.
- **Prerequisites:** env: TELEGRAM_BOT_TOKEN (for the living board)
- **Works without setup:** No in Hermes (not available in Claude)
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Drives a Hermes living board and cron cadence.
- **Size:** 23,679 B body, loaded when the skill triggers (~5,920 tokens); 122,549 B across 9 file(s) total
- **Path:** `skills/core/project-steward`

## recall

> **Not for Claude.** Reads Hermes session and memory stores, which Claude does not have.

- **Pack:** core
- **Scope:** solo
- **What it does:** Restore context from prior sessions, memories, and transcripts.
- **Use when:** a bare-pronoun follow-up like "ship it", "do it", or "send that" likely points at a prior-session artifact. Designed to never dead-end — if one source has nothing, keep searching others until you have a useful picture.
- **Prerequisites:** None
- **Works without setup:** Yes in Hermes (not available in Claude)
- **Compatibility:** Hermes-specific session and memory stores.
- **Claude:** unsupported — Reads Hermes session and memory stores, which Claude does not have.
- **Size:** 11,028 B body, loaded when the skill triggers (~2,757 tokens); 20,672 B across 4 file(s) total
- **Path:** `skills/core/recall`

## report

> **Not for Claude.** Uses Hermes reporting and routing tools.

- **Pack:** core
- **Scope:** fleet
- **What it does:** File a report or piece of feedback from any Hermes platform session.
- **Use when:** File a report or piece of feedback from any Hermes platform session.
- **Prerequisites:** None
- **Works without setup:** Yes in Hermes (not available in Claude)
- **Compatibility:** Hermes-specific reporting and routing tools.
- **Claude:** unsupported — Uses Hermes reporting and routing tools.
- **Size:** 11,568 B body, loaded when the skill triggers (~2,892 tokens); 30,517 B across 3 file(s) total
- **Path:** `skills/core/report`

## robustify-doctor

> **Not for Claude.** Inspects a Hermes runtime and HERMES_HOME layout.

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when you need to know whether a Hermes agent is actually healthy — during a scheduled health check, after an outage or reboot, when someone asks "is X working?", or when an agent has gone quiet.
- **Use when:** you need to know whether a Hermes agent is actually healthy — during a scheduled health check, after an outage or reboot, when someone asks "is X working?", or when an agent has gone quiet.
- **Prerequisites:** Python 3.9+ (stdlib only, no third-party packages), Read access to the target agent's HERMES_HOME
- **Works without setup:** No in Hermes (not available in Claude)
- **Compatibility:** Hermes-specific runtime and HERMES_HOME layout.
- **Claude:** unsupported — Inspects a Hermes runtime and HERMES_HOME layout.
- **Size:** 16,283 B body, loaded when the skill triggers (~4,071 tokens); 74,933 B across 4 file(s) total
- **Path:** `skills/core/robustify-doctor`

## skill-librarian

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when an agent's skill library needs auditing, cleaning, or triage - "audit my skills", "are my skills healthy", "find duplicate skills", "why didn't it use that skill", "clean up my skills", "which skills should this agent have", or after an upgrade adds new skills.
- **Use when:** an agent's skill library needs auditing, cleaning, or triage - "audit my skills", "are my skills healthy", "find duplicate skills", "why didn't it use that skill", "clean up my skills", "which skills should this agent have", or after an upgrade adds new skills.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Agent Skills standard
- **Claude:** degraded — Audits Hermes skill layout; the method transfers, the paths do not.
- **Size:** 13,065 B body, loaded when the skill triggers (~3,266 tokens); 91,532 B across 5 file(s) total
- **Path:** `skills/core/skill-librarian`

## trust-framework

- **Pack:** core
- **Scope:** solo
- **What it does:** Use to govern your own autonomy, deciding when to act on your own versus ask for approval, and earning more freedom over time the way a new employee earns trust through training and repetition.
- **Use when:** Use to govern your own autonomy, deciding when to act on your own versus ask for approval, and earning more freedom over time the way a new employee earns trust through training and repetition.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Portable governance rules; no runtime dependency.
- **Size:** 22,932 B body, loaded when the skill triggers (~5,733 tokens); 44,717 B across 6 file(s) total
- **Path:** `skills/core/trust-framework`

## address-pr-comments

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when a pull request has feedback from code-review bots (Cursor Bugbot, Codex, Claude Code Review, Greptile, CodeRabbit) or humans and you need to triage it, fix what is valid, push back on what is wrong, react and reply to every comment, and drive the PR to a clean, mergeable state.
- **Use when:** a pull request has feedback from code-review bots (Cursor Bugbot, Codex, Claude Code Review, Greptile, CodeRabbit) or humans and you need to triage it, fix what is valid, push back on what is wrong, react and reply to every comment, and drive the PR to a clean, mergeable state.
- **Prerequisites:** gh CLI, authenticated
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude Code with an authenticated gh CLI.
- **Size:** 19,751 B body, loaded when the skill triggers (~4,938 tokens); 63,432 B across 10 file(s) total
- **Path:** `skills/engineering/address-pr-comments`

## diagram-rendering

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when a fast hosted-render path is needed to turn D2, Mermaid, Graphviz, or Chart.js text into an inline-ready PNG for chat (Telegram, Discord, Slack) or a saved image.
- **Use when:** a fast hosted-render path is needed to turn D2, Mermaid, Graphviz, or Chart.js text into an inline-ready PNG for chat (Telegram, Discord, Slack) or a saved image.
- **Prerequisites:** chromium binary on PATH (or CHROMIUM_BIN) for local rasterize, network access to a Kroki host (KROKI_BASE) and QuickChart (QUICKCHART_BASE)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its render prerequisites exist.
- **Size:** 10,197 B body, loaded when the skill triggers (~2,549 tokens); 37,552 B across 4 file(s) total
- **Path:** `skills/engineering/diagram-rendering`

## mini-app

> **Not for Claude.** Operates Hermes-config mini-app host services.

- **Pack:** engineering
- **Scope:** fleet
- **What it does:** Use when adding, removing, password-protecting, or troubleshooting a mini-app served by the hermes-config mini-app router (Caddy + PM2 + auth sidecar + Tailscale Serve/Funnel) on a fleet machine.
- **Use when:** adding, removing, password-protecting, or troubleshooting a mini-app served by the hermes-config mini-app router (Caddy + PM2 + auth sidecar + Tailscale Serve/Funnel) on a fleet machine.
- **Prerequisites:** host services: Caddy + PM2, Tailscale Serve/Funnel
- **Works without setup:** No in Hermes (not available in Claude)
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Operates Hermes-config mini-app host services.
- **Size:** 45,652 B body, loaded when the skill triggers (~11,413 tokens); 87,321 B across 12 file(s) total
- **Path:** `skills/engineering/mini-app`

## pr-review-sweep

> **Not for Claude.** Depends on the Hermes delegation toolset.

- **Pack:** engineering
- **Scope:** fleet
- **What it does:** Nightly sweep of recently-merged PRs to address unhandled review comments via a Claude Code sub-agent.
- **Use when:** Nightly sweep of recently-merged PRs to address unhandled review comments via a Claude Code sub-agent.
- **Prerequisites:** gh CLI, authenticated, Hermes delegation toolset enabled
- **Works without setup:** No in Hermes (not available in Claude)
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Depends on the Hermes delegation toolset.
- **Size:** 8,107 B body, loaded when the skill triggers (~2,027 tokens); 52,992 B across 11 file(s) total
- **Path:** `skills/engineering/pr-review-sweep`

## email-steward

> **Not for Claude.** Depends on Hermes cron and delegation toolsets.

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when triaging one or more email inboxes on a schedule, removing obvious debris, quarantining promotional mail, and surfacing only messages that need the user's attention.
- **Use when:** triaging one or more email inboxes on a schedule, removing obvious debris, quarantining promotional mail, and surfacing only messages that need the user's attention.
- **Prerequisites:** email CLI: gog or himalaya, Hermes cron + delegation toolsets enabled
- **Works without setup:** No in Hermes (not available in Claude)
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Depends on Hermes cron and delegation toolsets.
- **Size:** 13,873 B body, loaded when the skill triggers (~3,468 tokens); 42,428 B across 12 file(s) total
- **Path:** `skills/productivity/email-steward`

## google-docs

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Use when:** creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Prerequisites:** gog CLI, authorized via `gog auth login`
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once the gog CLI is authorized.
- **Size:** 10,575 B body, loaded when the skill triggers (~2,644 tokens); 35,680 B across 5 file(s) total
- **Path:** `skills/productivity/google-docs`

## google-sheets

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, populating, formatting, importing, exporting, or quality-checking Google Sheets from CSV, JSON arrays, or computed tabular data.
- **Use when:** creating, populating, formatting, importing, exporting, or quality-checking Google Sheets from CSV, JSON arrays, or computed tabular data.
- **Prerequisites:** gog CLI, authorized for Google Sheets and Drive, python3, pdftoppm (poppler-utils), for multipage visual QA rasterization, uv, to run the XLSX verification snippets, openpyxl, via `uv run --with openpyxl` (not a standing install)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once the gog CLI is authorized.
- **Size:** 14,728 B body, loaded when the skill triggers (~3,682 tokens); 34,909 B across 4 file(s) total
- **Path:** `skills/productivity/google-sheets`

## google-slides

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, importing, exporting, or quality-checking Google Slides decks via markdown-to-PPTX conversion and Drive import.
- **Use when:** creating, importing, exporting, or quality-checking Google Slides decks via markdown-to-PPTX conversion and Drive import.
- **Prerequisites:** gog CLI, authorized via `gog auth login`, pandoc (for markdown conversion)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once the gog CLI is authorized.
- **Size:** 9,307 B body, loaded when the skill triggers (~2,327 tokens); 24,155 B across 2 file(s) total
- **Path:** `skills/productivity/google-slides`

## imessage-bluebubbles

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when sending, reading, or searching iMessages from an agent on macOS, or when setting up, hardening, or debugging the BlueBubbles iMessage bridge.
- **Use when:** sending, reading, or searching iMessages from an agent on macOS, or when setting up, hardening, or debugging the BlueBubbles iMessage bridge.
- **Prerequisites:** macOS with Messages.app signed into iMessage, BlueBubbles server app (installed by scripts/setup-bluebubbles.sh), Full Disk Access granted by hand (macOS permission prompts cannot be scripted), python3 with the requests package
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude on macOS once BlueBubbles is set up.
- **Size:** 21,156 B body, loaded when the skill triggers (~5,289 tokens); 84,352 B across 8 file(s) total
- **Path:** `skills/productivity/imessage-bluebubbles`

## vapi-calls

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Place and manage real outbound phone calls through the Vapi voice AI platform.
- **Use when:** an agent needs to reach a human by phone — a reminder, a confirmation, a question for a business, an appointment booking, or any errand that a voice conversation handles better than a message. Covers first-time setup, per-call configuration, live call control, and reading the result afterward.
- **Prerequisites:** env: VAPI_API_KEY (Vapi dashboard → API Keys, private key)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once VAPI_API_KEY is available.
- **Size:** 14,218 B body, loaded when the skill triggers (~3,554 tokens); 27,996 B across 2 file(s) total
- **Path:** `skills/productivity/vapi-calls`
