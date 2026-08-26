# A Grep Hit Is Not a Lever

Reading a key's _value_ out of a config file tells you nothing about whether
that key is live, legacy, or shadowed. The sandbox probe in the main SKILL.md
answers "what does this lever do." This file covers the step _before_ that:
**deciding which key is even the candidate.**

Fired 2026-08-05 on `max_iterations` during a fleet-wide iteration-limit bump.

## Trap 1 — similar-named keys at different nesting levels

One profile's `config.yaml` showed three plausible "iteration limit" hits:

```
74:  max_turns: 200          # under agent:
447:  max_iterations: 50      # under some other block
456:  max_turns: 200          # under yet another block
```

Line-number greps **flatten nesting**. Sibling keys look like duplicates, and a
nested key looks like the top-level one. Two same-named keys at different
indent levels are not a duplicate-key bug — they are different settings that
happen to share a name.

Before acting, establish:

1. **Which block does each hit belong to?** Read enough surrounding lines to
   recover the nesting, or load the YAML and walk the parsed structure.
2. **Which one does the runtime actually consume?** Grep the source for every
   candidate name and read the code that reads it.

Known live mapping worth checking against in Hermes: config `agent.max_turns`
becomes env `HERMES_MAX_ITERATIONS`. That means a differently-named
`max_iterations` key sitting a few hundred lines away may be **legacy and
change nothing when edited** — while looking like the obvious target.

Also check for a _ceiling_ relationship: raising key A while sibling key B
still caps the same behavior at a lower value is a no-op wearing a diff.

## Trap 2 — release notes name a behavior, not a key

> "The default tool-calling iteration limit jumped 90 → 500"

That sentence identifies a **behavior change**. It does not name a config key.
Mapping it onto the first similarly-named key in your config is a guess
dressed as a citation. The note may refer to a hardcoded default, a different
key, or a value with no user-facing config surface at all.

Grep the source for every candidate name, read the consuming code, and only
then decide which key the note meant.

## Why read-back verification does not save you

The failure mode is quiet and expensive:

1. You edit the dead key.
2. The file parses cleanly.
3. Read-back confirms the new value landed.
4. You report `12 of 12 profiles updated`.
5. Nothing changed.

**Read-back confirms the write, not the lever.** A verification checklist that
only re-reads the file cannot distinguish a live lever from a dead one. The
only thing that can is reading the code that consumes the key.

## Reporting discipline

When a value _looks_ stale, say so with the evidence you actually have:

- ✅ "Possibly stale — I read a grep line, not the consuming code."
- ❌ "That setting is stale."

The second is a claim you have not earned. Flagging your own unverified
observation as unverified, in the same breath you raise it, costs one clause
and prevents the whole downstream cascade.

## Corollary — delegating a config change

A competent subagent will faithfully do what you asked. If you ask it to set
key X to 500 across twelve hosts, it will, and it will hand you back a clean
denominator whether or not X does anything.

Make lever verification **Phase 1 with an explicit stop condition**:

> "Verify the lever first. Determine what `<key>` actually controls and its
> code default. Establish whether it is the live lever, a legacy/dead key, or a
> separate ceiling, and which one the release note refers to. Grep the source
> for both key names and read the code that consumes them. **If `<key>` turns
> out to be dead, or raising it without also raising `<sibling>` would be
> pointless or harmful, STOP and report that finding instead of editing.**
> Do not edit a lever you could not prove is live."

Pair it with a scope gate so the child cannot improvise past the finding:
config edits and backups authorized; no restarts, no model changes, no
installs, no opportunistic cleanup. If it believes a restart is required, that
comes back as a **finding**, not an action.

Require the report to name the source file and line numbers that prove the
Phase 1 conclusion. "I verified it" without a citation is the same unearned
claim, one level down.

## Checklist

- [ ] Nesting recovered for every grep hit; block membership established
- [ ] Every candidate key name grepped in the source
- [ ] Consuming code actually read, not inferred from the key name
- [ ] Sibling/ceiling relationships checked (does another key still cap this?)
- [ ] Release-note language mapped to a key by source, not by name similarity
- [ ] Unverified observations labeled unverified when first raised
- [ ] Delegated config work carries a Phase 1 stop condition and a scope gate
