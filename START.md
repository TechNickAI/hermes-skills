# Start here

You are helping a person add a few new skills to their AI. Begin warmly, explain each
skill in everyday language, and keep the person in control. Nothing changes until they
choose.

## Identify this runtime

Use the runtime's own system context and tools, not the binaries installed on the same
machine:

- **Hermes:** the runtime identifies itself as Hermes Agent and exposes Hermes tools, an
  active profile, or `HERMES_HOME`.
- **Claude Code:** the runtime identifies itself as Claude Code and exposes terminal,
  project tools, and `.claude/` skill paths.
- **Claude app / Cowork:** Claude chat, desktop, web, or Cowork without a local Claude Code
  project environment.

An installed `hermes` command does not prove the runtime is Hermes. If the answer remains
unclear, ask: "Are you running me in Hermes, Claude Code, or a Claude app?"

## Fetch one adapter

Follow only the adapter matching the runtime:

- **Hermes:** <https://raw.githubusercontent.com/TechNickAI/hermes-skills/main/install/hermes.md>
- **Claude Code, Claude app, or Cowork:**
  <https://raw.githubusercontent.com/TechNickAI/hermes-skills/main/install/claude-skills.md>

The adapter will lead you through a friendly catalog, runtime compatibility, approval,
installation, and verification. Do not invent a translation between runtimes; use the
compatibility notes and mappings provided by the repository.
