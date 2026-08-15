# hermes-skills

Skill library for [Hermes](https://github.com/NousResearch/hermes-agent) agents,
organized into **packs** so an agent installs what its role needs and nothing else.

## Why packs

Every installed skill costs context. Its name and description sit in the system
prompt on every single turn, and the model reads that list before it does
anything else.

Measured on a real 11-agent fleet: an agent carrying 281 skills spends ~6,250
tokens on the index before it reads a word of the actual task. One agent had
never once loaded **55%** of the skills it was carrying.

The token cost is survivable. The attention cost is the real problem — a model
choosing from 281 descriptions chooses worse than one choosing from 90.

So skills are grouped by the role that needs them, and an agent taps only its
packs.

## Packs

| Pack           | For                             | Contents                                                                 |
| -------------- | ------------------------------- | ------------------------------------------------------------------------ |
| `core`         | every agent, whatever its job   | research, review, memory, recall, reporting, health, autonomy governance |
| `engineering`  | agents that write and ship code | PR review triage, review sweeps, app-router operation                    |
| `productivity` | documents, comms, scheduling    | Google Docs/Sheets/Slides, iMessage, phone calls, inbox triage           |

A skill lives in exactly one pack. If two packs both seem right, the skill is
probably two skills.

## Installing

Tap the packs the agent needs:

```bash
hermes skills tap add TechNickAI/hermes-skills --path skills/core/
hermes skills tap add TechNickAI/hermes-skills --path skills/engineering/

hermes skills search <query>     # searches your tapped packs
hermes skills install <name>     # copies into ~/.hermes/skills/ and activates
```

Tapping makes a skill **discoverable**; installing puts it in the index. Those
are deliberately separate — tap broadly, install narrowly.

> Subscribing to more than one pack from the same repository needs Hermes with
> `(repo, path)` tap identity. Older builds dedupe on repo alone and silently
> keep only your first tap. Check with `hermes skills tap list`: if you added
> two packs and see one row, your build predates that fix.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

- **Zero PII.** No real names, hostnames, tailnet addresses, private domains, or
  absolute user paths. CI enforces this.
- **Pick the pack by what the skill does**, not by who happens to use it today.
- **Bump `version:`** on every content change, or installs read your update as a
  local customization and skip it.
- **Write what you verified**, including what you tried that did not work. A
  skill that documents a dead end saves the next agent the same hour.

## Related

- [`hermes-config`](https://github.com/TechNickAI/hermes-config) — setup: config,
  plugins, personality templates, infrastructure patterns
- `hermes-skills-private` — packs that cannot be published: environment-specific
  operations and alpha-bearing strategy

## License

MIT — see [LICENSE](LICENSE).
