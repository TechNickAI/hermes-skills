# Skill catalog

This file is generated from each skill's metadata. Do not edit it by hand.
Use it to choose a small set of relevant skills without opening every skill file.

`Claude` values: `native` (works fully), `degraded` (runs but loses its
differentiator — say so out loud), `unsupported` (never recommend it in Claude).

## deep-dive

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when told "do a deep dive", "go figure this out", or "don't reinvent the wheel" - researches a question across every relevant source and returns a decision.
- **Use when:** told "do a deep dive", "go figure this out", or "don't reinvent the wheel" - researches a question across every relevant source and returns a decision. Also fires on "see what everyone else is doing", "use all the skills you have", "what's the best way to X", "should we build this or buy it", "is th…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Portable to Hermes and Claude Code. In Claude, map the named research tools and delegation/panel mechanisms to available equivalents; unsupported source classes are reported, not silently omitted.
- **Claude:** degraded — Full method in Claude Code using its own web, file, and subagent tools; prior-session search and cross-family synthesis are unavailable.
- **Size:** 34,360 B always-loaded (~8,590 tokens); 34,360 B across 1 file(s) total
- **Path:** `skills/core/deep-dive`

## grok-search

- **Pack:** core
- **Scope:** solo
- **What it does:** On-demand real-time web and X (Twitter) search via xAI's Grok.
- **Use when:** On-demand real-time web and X (Twitter) search via xAI's Grok.
- **Prerequisites:** env: XAI_API_KEY (xAI console)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 5,499 B always-loaded (~1,375 tokens); 23,112 B across 4 file(s) total
- **Path:** `skills/core/grok-search`

## keep-going

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when the user says "/keep_going", "keep going", or "continue" after the agent has stopped short — asked "which option?", narrated a plan instead of executing it, or claimed a blocker that is not real — while the user has already given clear direction.
- **Use when:** the user says "/keep_going", "keep going", or "continue" after the agent has stopped short — asked "which option?", narrated a plan instead of executing it, or claimed a blocker that is not real — while the user has already given clear direction. Also use proactively when the agent notices it is abo…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Portable to Hermes, Claude Code, and similar coding agents.
- **Claude:** native — Works in Claude with no additional setup.
- **Size:** 3,453 B always-loaded (~863 tokens); 3,453 B across 1 file(s) total
- **Path:** `skills/core/keep-going`

## memory-cleanup

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when a Hermes MEMORY.md or USER.md file is too large, bloated, stale, or over the recommended cap and you need to reduce prompt footprint without losing important facts.
- **Use when:** a Hermes MEMORY.md or USER.md file is too large, bloated, stale, or over the recommended cap and you need to reduce prompt footprint without losing important facts. Applies a lossless memory diet: compress, relocate to SOUL.md/USER.md/AGENTS.md/context files, offload long-tail facts to the memory pr…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Hermes-specific memory-file layout and conventions.
- **Claude:** unsupported — Cleans Hermes MEMORY.md / USER.md / SOUL.md files, which do not exist in Claude.
- **Size:** 17,524 B always-loaded (~4,381 tokens); 50,529 B across 8 file(s) total
- **Path:** `skills/core/memory-cleanup`

## moa-solve

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when you have a HARD, open-ended, high-stakes problem worth throwing multiple AI models at and pulling the best solution out — architecture decisions, strategy design, thorny debugging, research synthesis, "what am I missing", tool/system design.
- **Use when:** you have a HARD, open-ended, high-stakes problem worth throwing multiple AI models at and pulling the best solution out — architecture decisions, strategy design, thorny debugging, research synthesis, "what am I missing", tool/system design. This is the SOLVE counterpart to multi-review (which criti…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Hermes-specific; requires the native MoA runtime.
- **Claude:** unsupported — Requires the native Hermes MoA fan-out runtime.
- **Size:** 19,681 B always-loaded (~4,920 tokens); 41,130 B across 5 file(s) total
- **Path:** `skills/core/moa-solve`

## mob-check

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when the user wants to know what real people are actually saying about a topic right now, not the SEO/editorial version.
- **Use when:** the user wants to know what real people are actually saying about a topic right now, not the SEO/editorial version. Pulls recent posts and engagement from Reddit, X, YouTube, Hacker News, Polymarket, GitHub, and the web, ranks by engagement and recency with a deterministic scorer, and writes one syn…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude with no additional setup.
- **Size:** 16,908 B always-loaded (~4,227 tokens); 58,589 B across 4 file(s) total
- **Path:** `skills/core/mob-check`

## multi-review

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when reviewing almost any meaningful artifact, decision, action, plan, code change, prompt, skill, research summary, outbound message, or public-facing content.
- **Use when:** reviewing almost any meaningful artifact, decision, action, plan, code change, prompt, skill, research summary, outbound message, or public-facing content. Runs a small panel of diverse review lenses across model families when available, synthesizes findings into fix/ask/defer/wontfix decisions, and…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Portable review method. Native multi-model orchestration examples are Hermes-specific; Claude can run the method with Claude subagents but loses model-family diversity.
- **Claude:** degraded — The review method transfers, but cross-model-family diversity needs Hermes; in Claude it becomes Claude reviewing Claude.
- **Size:** 48,649 B always-loaded (~12,162 tokens); 131,739 B across 17 file(s) total
- **Path:** `skills/core/multi-review`

## project-steward

- **Pack:** core
- **Scope:** solo
- **What it does:** Run a portfolio of long-running projects as a chief of staff rather than a task runner.
- **Use when:** you have several open-ended efforts that each need periodic attention, when scheduled agent runs are producing activity without progress, when a notification channel has become an unreadable wall of updates, or when you want an agent to direct specialist agents instead of doing their work. Covers th…
- **Prerequisites:** env: TELEGRAM_BOT_TOKEN (for the living board)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Drives a Hermes living board and cron cadence.
- **Size:** 23,679 B always-loaded (~5,920 tokens); 122,549 B across 9 file(s) total
- **Path:** `skills/core/project-steward`

## recall

- **Pack:** core
- **Scope:** solo
- **What it does:** Restore context from prior sessions, memories, and transcripts.
- **Use when:** a bare-pronoun follow-up like "ship it", "do it", or "send that" likely points at a prior-session artifact. Designed to never dead-end — if one source has nothing, keep searching others until you have a useful picture.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Hermes-specific session and memory stores.
- **Claude:** unsupported — Reads Hermes session and memory stores, which Claude does not have.
- **Size:** 11,028 B always-loaded (~2,757 tokens); 20,672 B across 4 file(s) total
- **Path:** `skills/core/recall`

## report

- **Pack:** core
- **Scope:** fleet
- **What it does:** File a report or piece of feedback from any Hermes platform session.
- **Use when:** File a report or piece of feedback from any Hermes platform session.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Hermes-specific reporting and routing tools.
- **Claude:** unsupported — Uses Hermes reporting and routing tools.
- **Size:** 11,568 B always-loaded (~2,892 tokens); 30,517 B across 3 file(s) total
- **Path:** `skills/core/report`

## robustify-doctor

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when you need to know whether a Hermes agent is actually healthy — during a scheduled health check, after an outage or reboot, when someone asks "is X working?", or when an agent has gone quiet.
- **Use when:** you need to know whether a Hermes agent is actually healthy — during a scheduled health check, after an outage or reboot, when someone asks "is X working?", or when an agent has gone quiet. Runs a deterministic collector that gathers facts across twelve subsystems, then reads those facts as an LLM t…
- **Prerequisites:** Python 3.9+ (stdlib only, no third-party packages), Read access to the target agent's HERMES_HOME
- **Works without setup:** No
- **Compatibility:** Hermes-specific runtime and HERMES_HOME layout.
- **Claude:** unsupported — Inspects a Hermes runtime and HERMES_HOME layout.
- **Size:** 16,283 B always-loaded (~4,071 tokens); 172,123 B across 7 file(s) total
- **Path:** `skills/core/robustify-doctor`

## skill-librarian

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when an agent's skill library needs auditing, cleaning, or triage - "audit my skills", "are my skills healthy", "find duplicate skills", "why didn't it use that skill", "clean up my skills", "which skills should this agent have", or after an upgrade adds new skills.
- **Use when:** an agent's skill library needs auditing, cleaning, or triage - "audit my skills", "are my skills healthy", "find duplicate skills", "why didn't it use that skill", "clean up my skills", "which skills should this agent have", or after an upgrade adds new skills. Finds broken skills that silently vani…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** degraded — Audits Hermes skill layout; the method transfers, the paths do not.
- **Size:** 13,065 B always-loaded (~3,266 tokens); 188,707 B across 7 file(s) total
- **Path:** `skills/core/skill-librarian`

## trust-framework

- **Pack:** core
- **Scope:** solo
- **What it does:** Use to govern your own autonomy, deciding when to act on your own versus ask for approval, and earning more freedom over time the way a new employee earns trust through training and repetition.
- **Use when:** Use to govern your own autonomy, deciding when to act on your own versus ask for approval, and earning more freedom over time the way a new employee earns trust through training and repetition.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude with no additional setup.
- **Size:** 22,932 B always-loaded (~5,733 tokens); 44,717 B across 6 file(s) total
- **Path:** `skills/core/trust-framework`

## address-pr-comments

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when a pull request has feedback from code-review bots (Cursor Bugbot, Codex, Claude Code Review, Greptile, CodeRabbit) or humans and you need to triage it, fix what is valid, push back on what is wrong, react and reply to every comment, and drive the PR to a clean, mergeable state.
- **Use when:** a pull request has feedback from code-review bots (Cursor Bugbot, Codex, Claude Code Review, Greptile, CodeRabbit) or humans and you need to triage it, fix what is valid, push back on what is wrong, react and reply to every comment, and drive the PR to a clean, mergeable state. Trigger phrases: "add…
- **Prerequisites:** gh CLI, authenticated
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 19,751 B always-loaded (~4,938 tokens); 63,432 B across 10 file(s) total
- **Path:** `skills/engineering/address-pr-comments`

## diagram-rendering

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when a fast hosted-render path is needed to turn D2, Mermaid, Graphviz, or Chart.js text into an inline-ready PNG for chat (Telegram, Discord, Slack) or a saved image.
- **Use when:** a fast hosted-render path is needed to turn D2, Mermaid, Graphviz, or Chart.js text into an inline-ready PNG for chat (Telegram, Discord, Slack) or a saved image. Handles the hosted-render + local-rasterize plumbing and platform gotchas (snap-chromium sandbox, D2-is-SVG-only, blank-render detection…
- **Prerequisites:** chromium binary on PATH (or CHROMIUM_BIN) for local rasterize, network access to a Kroki host (KROKI_BASE) and QuickChart (QUICKCHART_BASE)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 10,197 B always-loaded (~2,549 tokens); 37,552 B across 4 file(s) total
- **Path:** `skills/engineering/diagram-rendering`

## mini-app

- **Pack:** engineering
- **Scope:** fleet
- **What it does:** Use when adding, removing, password-protecting, or troubleshooting a mini-app served by the hermes-config mini-app router (Caddy + PM2 + auth sidecar + Tailscale Serve/Funnel) on a fleet machine.
- **Use when:** adding, removing, password-protecting, or troubleshooting a mini-app served by the hermes-config mini-app router (Caddy + PM2 + auth sidecar + Tailscale Serve/Funnel) on a fleet machine. Covers install, the Caddy route pattern, the auth sidecar conventions, exposing apps publicly via Funnel, Hermes…
- **Prerequisites:** host services: Caddy + PM2, Tailscale Serve/Funnel
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Operates Hermes-config mini-app host services.
- **Size:** 45,652 B always-loaded (~11,413 tokens); 87,321 B across 12 file(s) total
- **Path:** `skills/engineering/mini-app`

## pr-review-sweep

- **Pack:** engineering
- **Scope:** fleet
- **What it does:** Nightly sweep of recently-merged PRs to address unhandled review comments via a Claude Code sub-agent.
- **Use when:** Nightly sweep of recently-merged PRs to address unhandled review comments via a Claude Code sub-agent.
- **Prerequisites:** gh CLI, authenticated, Hermes delegation toolset enabled
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Depends on the Hermes delegation toolset.
- **Size:** 8,107 B always-loaded (~2,027 tokens); 52,992 B across 11 file(s) total
- **Path:** `skills/engineering/pr-review-sweep`

## email-steward

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when triaging one or more email inboxes on a schedule, removing obvious debris, quarantining promotional mail, and surfacing only messages that need the user's attention.
- **Use when:** triaging one or more email inboxes on a schedule, removing obvious debris, quarantining promotional mail, and surfacing only messages that need the user's attention. Provides a Hermes-native workflow using cron, per-message sub-agent isolation, deterministic header heuristics, account adapters, visi…
- **Prerequisites:** email CLI: gog or himalaya, Hermes cron + delegation toolsets enabled
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** unsupported — Depends on Hermes cron and delegation toolsets.
- **Size:** 13,873 B always-loaded (~3,468 tokens); 42,428 B across 12 file(s) total
- **Path:** `skills/productivity/email-steward`

## google-docs

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Use when:** creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Prerequisites:** gog CLI, authorized via `gog auth login`
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 10,575 B always-loaded (~2,644 tokens); 35,680 B across 5 file(s) total
- **Path:** `skills/productivity/google-docs`

## google-sheets

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, populating, formatting, importing, exporting, or quality-checking Google Sheets from CSV, JSON arrays, or computed tabular data.
- **Use when:** creating, populating, formatting, importing, exporting, or quality-checking Google Sheets from CSV, JSON arrays, or computed tabular data.
- **Prerequisites:** gog CLI, authorized for Google Sheets and Drive, python3, pdftoppm (poppler-utils), for multipage visual QA rasterization, uv, to run the XLSX verification snippets, openpyxl, via `uv run --with openpyxl` (not a standing install)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 14,728 B always-loaded (~3,682 tokens); 34,909 B across 4 file(s) total
- **Path:** `skills/productivity/google-sheets`

## google-slides

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, importing, exporting, or quality-checking Google Slides decks via markdown-to-PPTX conversion and Drive import.
- **Use when:** creating, importing, exporting, or quality-checking Google Slides decks via markdown-to-PPTX conversion and Drive import.
- **Prerequisites:** gog CLI, authorized via `gog auth login`, pandoc (for markdown conversion)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 9,307 B always-loaded (~2,327 tokens); 24,155 B across 2 file(s) total
- **Path:** `skills/productivity/google-slides`

## imessage-bluebubbles

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when sending, reading, or searching iMessages from an agent on macOS, or when setting up, hardening, or debugging the BlueBubbles iMessage bridge.
- **Use when:** sending, reading, or searching iMessages from an agent on macOS, or when setting up, hardening, or debugging the BlueBubbles iMessage bridge. Also use when an existing chat.db/imsg approach breaks with permissionDenied, "authorization denied (code 23)", or hangs with no output after a macOS or Pytho…
- **Prerequisites:** macOS with Messages.app signed into iMessage, BlueBubbles server app (installed by scripts/setup-bluebubbles.sh), Full Disk Access granted by hand (macOS permission prompts cannot be scripted), python3 with the requests package
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 21,156 B always-loaded (~5,289 tokens); 84,352 B across 8 file(s) total
- **Path:** `skills/productivity/imessage-bluebubbles`

## vapi-calls

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Place and manage real outbound phone calls through the Vapi voice AI platform.
- **Use when:** an agent needs to reach a human by phone — a reminder, a confirmation, a question for a business, an appointment booking, or any errand that a voice conversation handles better than a message. Covers first-time setup, per-call configuration, live call control, and reading the result afterward.
- **Prerequisites:** env: VAPI_API_KEY (Vapi dashboard → API Keys, private key)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once its prerequisites are met.
- **Size:** 14,218 B always-loaded (~3,554 tokens); 27,996 B across 2 file(s) total
- **Path:** `skills/productivity/vapi-calls`
