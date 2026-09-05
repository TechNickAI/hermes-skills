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

## check-upstream-first

- **Pack:** core
- **Scope:** solo
- **What it does:** Use before debugging a framework or dependency bug from its source, and before writing any local patch.
- **Use when:** Use before debugging a framework or dependency bug from its source, and before writing any local patch.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Version-then-issue-tracker method works anywhere with a shell and network.
- **Size:** 50,649 B body, loaded when the skill triggers (~12,662 tokens); 156,390 B across 16 file(s) total
- **Path:** `skills/core/check-upstream-first`

## data-verification

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when data will drive a decision: is it profitable, did X cause Y, which cohort wins.
- **Use when:** data will drive a decision: is it profitable, did X cause Y, which cohort wins. Load BEFORE reporting any number, rate, P&L, backtest result, metrics review, cost model, funnel, or A/B outcome.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Stdlib-only check library and eval harness; the protocol needs no Hermes runtime.
- **Size:** 23,905 B body, loaded when the skill triggers (~5,976 tokens); 72,717 B across 2 file(s) total
- **Path:** `skills/core/data-verification`

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

## delegation-handoff

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when handing work to a background agent or subprocess, or when one comes back reporting success.
- **Use when:** handing work to a background agent or subprocess, or when one comes back reporting success. Covers verifying the premise before dispatch, writing a brief the worker can finish inside its budget, and checking the artifact yourself afterward.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Agent Skills standard
- **Claude:** degraded — The briefing and artifact-verification discipline transfers; the background-dispatch examples assume a delegation toolset.
- **Size:** 18,433 B body, loaded when the skill triggers (~4,608 tokens); 30,626 B across 3 file(s) total
- **Path:** `skills/core/delegation-handoff`

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

## is-it-really-broken

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when a health check, audit, or monitor says something is BROKEN, before repeating that to anyone.
- **Use when:** a health check, audit, or monitor says something is BROKEN, before repeating that to anyone.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Re-probing a failure verdict needs no host runtime beyond the failing check.
- **Size:** 17,981 B body, loaded when the skill triggers (~4,495 tokens); 47,582 B across 6 file(s) total
- **Path:** `skills/core/is-it-really-broken`

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
- **Size:** 17,524 B body, loaded when the skill triggers (~4,381 tokens); 50,530 B across 8 file(s) total
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
- **Size:** 19,679 B body, loaded when the skill triggers (~4,920 tokens); 41,132 B across 5 file(s) total
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
- **Size:** 16,906 B body, loaded when the skill triggers (~4,226 tokens); 58,587 B across 4 file(s) total
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
- **Size:** 54,440 B body, loaded when the skill triggers (~13,610 tokens); 150,895 B across 18 file(s) total
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

## prove-the-setting-works

- **Pack:** core
- **Scope:** solo
- **What it does:** Use when about to tell someone a config change will (or will not) do what they want — hide a UI element, disable a provider, silence a channel, pin a new model version.
- **Use when:** about to tell someone a config change will (or will not) do what they want — hide a UI element, disable a provider, silence a channel, pin a new model version. Copies the config to a throwaway profile, changes one setting, re-runs the real code path, and reads the actual output.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Sandbox-probe method is runtime-agnostic; it needs only a copyable config and the ability to re-run the real code path.
- **Size:** 45,256 B body, loaded when the skill triggers (~11,314 tokens); 134,975 B across 16 file(s) total
- **Path:** `skills/core/prove-the-setting-works`

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
- **Size:** 11,028 B body, loaded when the skill triggers (~2,757 tokens); 20,674 B across 4 file(s) total
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
- **Size:** 11,566 B body, loaded when the skill triggers (~2,892 tokens); 30,513 B across 3 file(s) total
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
- **Size:** 16,281 B body, loaded when the skill triggers (~4,070 tokens); 74,931 B across 4 file(s) total
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
- **Size:** 13,065 B body, loaded when the skill triggers (~3,266 tokens); 91,517 B across 5 file(s) total
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
- **Size:** 22,945 B body, loaded when the skill triggers (~5,736 tokens); 44,734 B across 6 file(s) total
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
- **Size:** 19,743 B body, loaded when the skill triggers (~4,936 tokens); 63,412 B across 10 file(s) total
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
- **Size:** 10,197 B body, loaded when the skill triggers (~2,549 tokens); 37,554 B across 4 file(s) total
- **Path:** `skills/engineering/diagram-rendering`

## find-the-real-bottleneck

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when something in a multi-layer stack is slow, memory-hungry, or expensive and you need to prove WHERE the cost actually originates before recommending a fix — a slow dashboard fronting a busy proxy, a request path spanning client → gateway → router → upstream API, a process whose RSS keeps climbing, a spend spike whose obvious explanation doesn't survive arithmetic.
- **Use when:** something in a multi-layer stack is slow, memory-hungry, or expensive and you need to prove WHERE the cost actually originates before recommending a fix — a slow dashboard fronting a busy proxy, a request path spanning client → gateway → router → upstream API, a process whose RSS keeps climbing, a…
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Measuring each hop in a causal chain needs only a shell and the system under test.
- **Size:** 39,963 B body, loaded when the skill triggers (~9,991 tokens); 141,559 B across 16 file(s) total
- **Path:** `skills/engineering/find-the-real-bottleneck`

## live-database-maintenance

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when cleaning up, compacting, backing up, or restoring a SQLite database that a running service still holds open, or when one reports "database disk image is malformed".
- **Use when:** cleaning up, compacting, backing up, or restoring a SQLite database that a running service still holds open, or when one reports "database disk image is malformed".
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — SQLite maintenance and corruption triage are runtime-agnostic; the bundled scripts are stdlib Python.
- **Size:** 41,899 B body, loaded when the skill triggers (~10,475 tokens); 322,320 B across 36 file(s) total
- **Path:** `skills/engineering/live-database-maintenance`

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
- **Size:** 45,642 B body, loaded when the skill triggers (~11,410 tokens); 87,298 B across 12 file(s) total
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
- **Size:** 8,107 B body, loaded when the skill triggers (~2,027 tokens); 53,009 B across 11 file(s) total
- **Path:** `skills/engineering/pr-review-sweep`

## scheduled-job-runner

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when creating, migrating, debugging, or reviewing Hermes cron jobs.
- **Use when:** creating, migrating, debugging, or reviewing Hermes cron jobs. Ships a tested execution adapter for interpreter resolution, overlap prevention, hard timeouts, quiet success, structured ledgers, bounded redacted logs, failure notification, run severity, and heartbeat reporting.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Agent Skills standard
- **Claude:** degraded — The runner and its exit-code contract are portable Python; the cron wiring examples assume a scheduler that dispatches by file extension.
- **Size:** 9,071 B body, loaded when the skill triggers (~2,268 tokens); 205,256 B across 10 file(s) total
- **Path:** `skills/engineering/scheduled-job-runner`

## stop-the-noise

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when something is sending repeated, unwanted, or unread messages — a scheduled job that reports every run, a webhook firing once per event, progress commentary nobody asked for.
- **Use when:** something is sending repeated, unwanted, or unread messages — a scheduled job that reports every run, a webhook firing once per event, progress commentary nobody asked for. Finds which source is actually producing the messages and silences it without muting real alerts.
- **Prerequisites:** None
- **Works without setup:** Yes, but read the Claude note before recommending it
- **Compatibility:** Agent Skills standard
- **Claude:** degraded — Diagnosing and silencing a noisy source transfers; the scheduled-job and gateway examples assume a long-running agent runtime.
- **Size:** 27,618 B body, loaded when the skill triggers (~6,904 tokens); 157,266 B across 14 file(s) total
- **Path:** `skills/engineering/stop-the-noise`

## upgrade-a-live-service-safely

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when upgrading, rebuilding, or redeploying a service that is CURRENTLY SERVING production traffic — an LLM router, API gateway, web app, or any long-running daemon on a host you reach over SSH.
- **Use when:** upgrading, rebuilding, or redeploying a service that is CURRENTLY SERVING production traffic — an LLM router, API gateway, web app, or any long-running daemon on a host you reach over SSH.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Stage-verify-cut-rollback sequencing applies to any supervised service.
- **Size:** 70,019 B body, loaded when the skill triggers (~17,505 tokens); 380,692 B across 42 file(s) total
- **Path:** `skills/engineering/upgrade-a-live-service-safely`

## vendor-switch-check

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when evaluating a new vendor, tool, or platform, or when someone proposes replacing one you already run.
- **Use when:** evaluating a new vendor, tool, or platform, or when someone proposes replacing one you already run. Tries to falsify the claimed advantage first — verify the capability exists on your actual plan, measure it on the real path, and price the switching cost — before designing any migration.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Falsify-the-claim-first evaluation needs only the vendor's own API and a shell.
- **Size:** 13,369 B body, loaded when the skill triggers (~3,342 tokens); 26,220 B across 4 file(s) total
- **Path:** `skills/engineering/vendor-switch-check`

## writing-for-non-engineers

- **Pack:** engineering
- **Scope:** solo
- **What it does:** Use when writing a plan, status report, incident summary, or recommendation for someone who does not work in the system being described.
- **Use when:** writing a plan, status report, incident summary, or recommendation for someone who does not work in the system being described. Leads with what changed for them, keeps the technical detail underneath, and gives them at most one real decision to make.
- **Prerequisites:** None
- **Works without setup:** Yes
- **Compatibility:** Agent Skills standard
- **Claude:** native — Writing guidance with no runtime dependency at all.
- **Size:** 19,622 B body, loaded when the skill triggers (~4,906 tokens); 33,484 B across 4 file(s) total
- **Path:** `skills/engineering/writing-for-non-engineers`

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
- **Size:** 13,873 B body, loaded when the skill triggers (~3,468 tokens); 42,438 B across 12 file(s) total
- **Path:** `skills/productivity/email-steward`

## fieldy

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when reading conversations, transcripts, summaries, or action items captured by a Fieldy AI wearable note taker, or when the user mentions Fieldy, their wearable, or wants the record of something said in person rather than on a video call.
- **Use when:** reading conversations, transcripts, summaries, or action items captured by a Fieldy AI wearable note taker, or when the user mentions Fieldy, their wearable, or wants the record of something said in person rather than on a video call.
- **Prerequisites:** env: FIELDY_API_KEY (Fieldy app → Settings → Developer Settings), Python 3.9+ (stdlib only, no third-party packages)
- **Works without setup:** No
- **Compatibility:** Agent Skills standard. The bundled client is stdlib-only Python and needs no Hermes runtime; any agent that can run python3 and read an env var can use it.
- **Claude:** native — Stdlib-only REST client; works in Claude once FIELDY_API_KEY is available.
- **Size:** 15,306 B body, loaded when the skill triggers (~3,826 tokens); 89,919 B across 3 file(s) total
- **Path:** `skills/productivity/fieldy`

## google-docs

- **Pack:** productivity
- **Scope:** solo
- **What it does:** Use when creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Use when:** creating, importing, formatting, editing, exporting, or quality-checking Google Docs from agent-generated markdown or local files.
- **Prerequisites:** gog CLI, authorized via `gog auth login`
- **Works without setup:** No
- **Compatibility:** Agent Skills standard
- **Claude:** native — Works in Claude once the gog CLI is authorized.
- **Size:** 10,577 B body, loaded when the skill triggers (~2,644 tokens); 35,683 B across 5 file(s) total
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
- **Size:** 14,724 B body, loaded when the skill triggers (~3,681 tokens); 34,905 B across 4 file(s) total
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
- **Size:** 9,305 B body, loaded when the skill triggers (~2,326 tokens); 24,153 B across 2 file(s) total
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
- **Size:** 21,144 B body, loaded when the skill triggers (~5,286 tokens); 84,340 B across 8 file(s) total
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
- **Size:** 14,216 B body, loaded when the skill triggers (~3,554 tokens); 27,988 B across 2 file(s) total
- **Path:** `skills/productivity/vapi-calls`
