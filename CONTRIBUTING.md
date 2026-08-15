# Contributing

## The one rule that matters: zero PII

This repository is public. Nothing in it may identify a real person, machine, or
private network. CI runs a scanner on every PR and blocks the merge.

### Substitution table

| Instead of                                   | Write                                                         |
| -------------------------------------------- | ------------------------------------------------------------- |
| a real person's name                         | `<user>`, or a neutral placeholder (`atlas`, `scout`, `vega`) |
| a real hostname                              | `<host>`, `mac-mini`, `build-box`                             |
| a tailnet address (`100.x.y.z`)              | `100.100.100.100` or `<tailnet-ip>`                           |
| a private domain                             | `example.com`                                                 |
| `/Users/yourname/...`                        | `/Users/<user>/...`                                           |
| an agent or persona name                     | a neutral placeholder                                         |
| an exact incident date tied to a real outage | "on one occasion", or drop it                                 |

Agent and persona names count as fleet identifiers. A public skill that names
the roster leaks it just as surely as one that lists hostnames.

### Scrub before you stage

Run the scanner locally, then read the diff yourself:

```bash
python3 scripts/pii_scan.py skills/
```

A clean scan is necessary, not sufficient. The scanner catches patterns it knows
about; it cannot catch a paragraph that describes your specific deployment in
identifying detail. Read what you wrote.

## Picking a pack

Choose by **what the skill does**, not who uses it today.

- `core` — would an agent of any role reach for this? Research, review, memory,
  recall, reporting, self-diagnosis, autonomy governance.
- `engineering` — writing, reviewing, shipping, and hosting code.
- `productivity` — documents, messaging, telephony, scheduling, inboxes.

Reach across a fleet is corroborating evidence, not the deciding factor. A skill
installed on one agent may still be universal — it may simply be new.

**A skill lives in exactly one pack, and in exactly one repository.** Two copies
of a skill name diverge, and the loader cannot tell which one you meant. When
only part of a skill is environment-specific, split along that seam: the generic
technique here, the specifics in the private repo, cross-referenced.

### When a skill belongs in the private repo instead

Three tests. Any one of them is disqualifying:

1. **Not reasonably generalizable** — it only makes sense against one specific
   deployment, and placeholders would leave nothing useful.
2. **Proprietary or alpha-bearing** — publishing destroys the value. Trading
   strategy, screening criteria, financial decision rules.
3. **Unavoidably PII-dense** — the content _is_ an inventory of who runs what,
   not merely a doc that mentions a hostname.

"Contains a hostname" is not one of these. Scrub it and publish.

## Skill format

Frontmatter, then the body:

```yaml
---
name: my-skill
version: 1.0.0
description: >
  Use when <trigger>. <What it does in one line.>
license: MIT
metadata:
  hermes:
    requires:
      - "external service or binary this needs"
    tags: [topic, tool]
    related_skills: [other-skill]
---
```

- **`description` decides whether the skill is ever loaded.** It sits in the
  system prompt; the body does not. Lead with the trigger condition. "Use when
  X" beats "A tool for X".
- **`requires`** lists what must exist for the skill to work. Omitting it makes
  the manifest advertise `works_out_of_the_box: true`, and a setup agent will
  install it freely — then it fails on first use.
- **`version`** must be bumped on every content change. Update checks compare
  versions; an unbumped change reads as "same version, different content" and
  gets treated as local customization.
- **`related_skills`** must resolve within this repo, or be listed in a comment
  as intentionally external. CI checks this.

## Writing a skill worth loading

Write for an agent that has never seen the system and cannot ask you a question.

- **Numbered steps with exact commands.** Not "configure the router" but the
  command, its expected output, and how to tell it worked.
- **A pitfalls section.** The traps you actually hit. This is usually the most
  valuable part — anyone can write the happy path.
- **Verification.** How to prove the thing worked, from the user-visible
  outcome, not from an exit code.
- **Record dead ends.** "X looks like it should work; it does not, because Y"
  saves the next agent an hour.

Prefer a skill that is honest about its limits over one that sounds
authoritative. An agent will follow what you write.

## Pull requests

1. Branch, make the change, bump `version:`
2. `python3 scripts/pii_scan.py skills/` — must be clean
3. `python3 scripts/generate_manifest.py` — regenerate
4. Run the tests
5. Open the PR; fix what review finds; re-run

Do not merge your own PR.
