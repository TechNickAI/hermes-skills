# Naming UI Surfaces for Non-Technical Users

Companion reference. `prove-the-setting-works` answers _what can I change?_;
this answers _what should it say once I can?_

Applies whenever interface text — menu labels, button names, command options,
model/combo aliases — is read by someone who does not know the architecture.
Derived from a `/models` picker curation session.

The same audience discipline applies to _messages_. This is that discipline
applied to _nouns in a UI_,
where the failure is easier to miss because nobody is "writing a message."

## The core failure: naming by provenance instead of by job

Default UI naming describes **who built a thing** or **how it is plumbed**.
Users are asking **which one do I pick?** Vendor and transport names answer
neither.

Real picker labels, and what each actually communicated to a non-technical
operator:

| label             | what it answers                | what she asked       |
| ----------------- | ------------------------------ | -------------------- |
| the router        | our router's product name      | which one do I pick? |
| Anthropic         | who owns the lab               | "                    |
| OpenAI            | who owns the lab               | "                    |
| OpenRouter Direct | two pieces of transport trivia | "                    |
| Mixture of Agents | our architecture               | "                    |

The unlocking question, from the operator: **"Pretend you are Ali or an owner, what
should these labels be?"** Answer from inside the user's head, not from the
config file.

"Direct" was the worst offender — a comparative with no visible referent. It
only parses if you already know what it is direct _versus_, which is precisely
the knowledge the label was supposed to supply.

## Naming rubric

1. **Name by job, not by vendor or transport.** The label should help someone
   choose without knowing the architecture.
2. **Use the brand the user has actually heard of.** "Claude" and "ChatGPT"
   beat "Anthropic" and "OpenAI" for a consumer audience — recognition is the
   entire point.
3. **Point at the default.** One row named "Recommended" lets anyone who does
   not want to decide, not decide. Removing a decision beats explaining it.
4. **Label the junk drawer as a junk drawer.** "Other models" is honest and
   correctly sorts to the bottom of attention.
5. **Keep honest warnings short enough to fit.** "(direct)" signals "bypasses
   the normal path" in one button-sized token. Do not hide the caveat; do not
   spend a paragraph on it.

Worked example (proposed for the operations agent, presented to the operator):

| current           | proposed         |
| ----------------- | ---------------- |
| the router        | Recommended      |
| Anthropic         | Claude (direct)  |
| OpenAI            | ChatGPT (direct) |
| OpenRouter Direct | Other models     |
| Mixture of Agents | Panel of experts |

## ⚠️ Propose the rubric, but let the owner name his own infrastructure

the operator accepted the rubric and then **overrode half the names** — twice. The
final labels were `the router` (not "Recommended") and
`OpenRouter (other models)` (not "Other models"), and `Mixture of Agents` was
explicitly left alone.

The pattern in his edits: he kept the **real system name as the anchor** and
let the plain-language part ride alongside it in parentheses. Renaming
`the router` to a pure job label erased a proper noun he uses daily and thinks
in — the abstraction cost him more than it saved a member.

Rules learned:

- **A rubric is a proposal, not a decision.** Present the reasoning and the
  candidate names, then apply what the owner picks — do not relitigate.
- **Do not rename a system the owner personally operates.** Job-based labels are
  for lanes the user should not have to think about; named infrastructure
  (the router, OpenRouter) is vocabulary he already owns.
- **`Name (plain description)` is the preferred compromise shape.** It keeps the
  real identifier searchable and greppable while adding the human hint.
- **Ask before abstracting away a proper noun.** Cheap to ask, and the answer is
  not derivable from the rubric.

The earlier rubric still holds for lanes with no established name. It does not
override the owner's naming of his own stack.

## Establish the relabelable surface FIRST

Do not design a naming scheme you cannot ship. Probe the constraint surface
before proposing names — use `scripts/probe_config_lever.py`.

Measured in the Hermes picker (v0.19.0): **provider rows are relabelable,
individual model buttons are not.** A plausible-looking shape
(`models: [{id:..., name:...}]`) silently does nothing, because `name` is
parsed as an _ID fallback_ consulted only when `id` is absent. Nothing errors;
the button still renders the raw identifier.

Generalize: when a naming request arrives, establish which layers accept a
display name and which render a raw identifier, then report that boundary. A
half-deliverable promise ("I'll clean up the labels") breaks on delivery.

## Presentation is per-audience; routing is fleet-wide

A split that cuts against the usual parity instinct:

- **Routing config** (billing lanes, quota, combos, model IDs) → fleet parity is
  correct; drift is a bug.
- **Presentation** (labels, which rows are visible at all) → parity is _wrong_.
  The right answer depends on who is reading.

A non-technical owner may be best served by a **single** "Recommended" row with
escape hatches hidden entirely. Escape hatches exist for the person who knows
what they are bypassing. Profiles need not match; proposing one canonical menu
fleet-wide is a failure to model the audience.

## Sequence label work separately from identifier work

When both the labels and the underlying identifiers are bad, split them and
price them separately:

1. **Display labels** — local, cheap, reversible, per-profile. Do now.
2. **Underlying identifiers** (combo names, command names, model aliases) —
   higher leverage, because they are what users actually click, but pinned
   across configs, cron jobs, and docs; a rename can fail at request time with
   no fallback. Plan the rollout before renaming.

**Do not present these as one bundle.** Bundling invites a yes to the risky half
on the strength of the safe half. Name the cheap win, name the expensive one,
let the user sequence them.

## Litmus test

- [ ] Does this help someone _choose_, or just say who built it?
- [ ] Would the intended user recognize every word without explanation?
- [ ] Is there a clearly-marked default for someone who does not want to decide?
- [ ] Did I verify this layer actually accepts a custom label?
- [ ] Am I curating for THIS audience, or copying another profile's menu?
- [ ] Are cheap label changes separated from risky identifier renames?
