---
name: prove-the-setting-works
description: >
  Use when about to tell someone a config change will (or will not) do what they
  want — hide a UI element, disable a provider, silence a channel, pin a new model
  version. Copies the config to a throwaway profile, changes one setting, re-runs
  the real code path, and reads the actual output. Prevents promising a fix that
  silently does nothing, and prevents calling something impossible when a
  different setting would have worked.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [config, verification, sandbox, probe, methodology]
    related_skills:
      - check-upstream-first
      - is-it-really-broken
---

# Prove the Setting Works

## Overview

A config key's NAME is not evidence of its BEHAVIOR. Neither is its docstring,
nor a rule you wrote in memory six months ago.

Two symmetrical failures keep recurring:

- **False positive:** "Set `enabled: false` and the row disappears." It loads
  without error, looks applied, and silently does nothing.
- **False negative:** "That can't be done with config." Said after reading one
  code path, when a different lever would have worked.

Both are cured by the same three-minute move: **mutate a throwaway copy, run
the real code path, read the real output.**

The rule: _never describe a config change's effect you have not observed._

## When to Use

- Before promising a config-only fix ("I can hide that with a setting").
- Before declaring a limit ("that needs an upstream change").
- Before removing a config block that something else might reference.
- When a standing rule in memory would block an approach — test whether the
  rule is actually as broad as it was written.
- After any config edit, to confirm the observable behavior changed.

## The sandbox probe

Never edit the live config to find out what a key does.

1. **Copy the config into a throwaway home.**

   ```python
   TMP = pathlib.Path(tempfile.mkdtemp(prefix="probe_"))
   shutil.copy(SRC / "config.yaml", TMP / "config.yaml")
   ```

2. **Mutate exactly one lever** with a round-tripping parser so unrelated
   formatting is preserved:

   ```python
   y = ruamel.yaml.YAML(); y.preserve_quotes = True; y.width = 4096
   ```

3. **Run the REAL code path** — the same function the product calls, not a
   reimplementation — pointed at the sandbox:

   ```bash
   HERMES_HOME=$TMP <the-app-interpreter> probe.py
   ```

   Use the application's own interpreter. A system `python3` will not have the
   package importable and its failure will look like a config problem.

4. **Read the output, not the exit code.** Exit 0 proves it ran, not that the
   lever worked.

5. **Diff against an unmutated run.** Without a baseline you cannot tell a
   working lever from a coincidence.

Package the probe as a `scripts/` file in the governing skill so the next
session runs it instead of rewriting it.

**Ready-made harness: `scripts/probe_config_lever.py`.** Provides `baseline()`,
`probe(mutate, code, note=...)`, and `matrix([...], code)` — the last probes
several levers at once and prints a `NO-OP (same as baseline)` / `changed`
summary, so a silently-ignored setting is impossible to miss. Run the file
directly for a self-check of the interpreter and profile paths.

## Capability-coupled levers: turning a thing OFF can disable what you wanted ON

Before reaching for the obvious "disable it" lever, ask what ELSE that flag
gates. Platforms, integrations and providers routinely bundle two independent
concerns behind one boolean:

- **wiring** — is this transport configured and usable for OUTBOUND work?
- **admission policy** — what happens when an UNKNOWN party contacts us inbound?

Operators reach for `enabled: false` to fix an inbound problem and silently
destroy the outbound capability they were relying on.

Verified 2026-08-22: an agent was texting **pairing codes to a real owner's real
contacts** over iMessage. The local remedy set `bluebubbles.enabled: false`,
which stopped the codes AND made the send path refuse
(`tools/send_message_tool.py` bails on `not pconfig.enabled`). The agent lost
outbound iMessage entirely, and nobody noticed for over a week, because the
reported symptom had gone away.

**Probe BOTH properties as a pair.** A lever matrix with one column is how you
ship a fix that quietly breaks the feature:

| configuration                            | inbound: pairs with strangers? | outbound: can send?      |
| ---------------------------------------- | ------------------------------ | ------------------------ |
| credentials only (the incident)          | **yes**                        | yes                      |
| `enabled: false`                         | no                             | **NO — capability lost** |
| `extra.unauthorized_dm_behavior: ignore` | no                             | yes ✅                   |
| per-platform allowlist env var           | no                             | yes ✅                   |

The two bottom rows are the real fix; row two is the trap. Write the harness so
each case reports a tuple, never a single boolean.

### `extra:` is a second floor of silent no-op

Nesting failure has a sub-level. Even at the correct
`gateway.platforms.<name>` depth, some keys are only read from an `extra:`
sub-map. One level up — the obvious, human-looking place — the key parses,
persists, round-trips through the config reader, and is **never consulted**:

```yaml
# SILENTLY IGNORED — parses fine, reads back fine, does nothing
platforms:
  bluebubbles:
    unauthorized_dm_behavior: ignore

# ACTUALLY READ
platforms:
  bluebubbles:
    enabled: true
    extra:
      unauthorized_dm_behavior: ignore
```

This is a prime reason a working config lever gets misdiagnosed as "impossible,
needs a source patch." Before concluding a framework must be forked, probe the
key at **every** plausible depth — top-level, platform-level, and
`platform.extra` — and read the value back through the product's own getter.

### Find the carve-out that already exists

When arguing a default is wrong for your case, search the resolver for a sibling
that already got an exception. Upstream had already special-cased email:
_"inboxes may contain arbitrary unread human messages, so replying with pairing
codes is not a safe platform default"_ — verbatim the argument for iMessage. An
existing carve-out is the strongest upstream evidence available: maintainers
already accepted the principle, so you are extending settled reasoning rather
than proposing new policy.

### "I refuse to believe the fix is to hack the source"

Treat that instinct as correct until a full lever matrix disproves it. A local
source patch to a framework is a liability: it silently reverts on every
upgrade, it hides in `git status` as "dirty tree" that a future rollout will
reset, and — as above — it can encode a workaround that disables real
functionality. When someone insists a config path must exist, the probe is the
cheap way to find it, not the expensive way to prove them wrong.

Order of preference, always: **config lever → upstream PR changing the default →
local patch (last resort, with an expiry plan).**

Full probe harness, end-to-end reproduction with positive control, and the
outbound-send gate: `references/platform-enable-vs-inbound-policy.md`.

## Test the matrix, not one hypothesis

When the goal is "make X not appear," enumerate every plausible lever and test
them together. A single failed attempt is not proof of impossibility.

Worked example — hiding a UI row, all four attempts probed before reporting:

| attempt                          | result                                       |
| -------------------------------- | -------------------------------------------- |
| add it to the exclusion list     | still shown                                  |
| `enabled: false` on the feature  | still shown                                  |
| `enabled: false` on the sub-item | still shown                                  |
| delete the whole config block    | still shown, AND fell back to stale defaults |

Only after that matrix is the claim "this needs an upstream change" honest — and
it now comes with the evidence attached. Note the fourth row: the most
aggressive option was the most _harmful_, because deletion triggered a
synthesized default rather than absence. Probing found that; reasoning would
not have.

## Config shapes that look right and silently no-op

Parsers are forgiving in ways that hide mistakes. Two live examples:

- **A key stripped by a normalizer.** An unknown key can be dropped during load
  while everything still "works." Verify by reading the _loaded dict_, not the
  file you wrote. (Inverse also happens: a warning that a key was ignored can be
  cosmetic while the key survives — check, don't assume either way.)
- **A field parsed as something other than a label.** A shape like
  `[{id: "x", name: "Friendly Name"}]` can look like a display-name mechanism
  while `name` is really an _ID fallback_ consulted only when `id` is missing.
  The friendly name never renders and nothing errors.

- **The right key at the wrong NESTING LEVEL.** The name is correct, the value
  is correct, `hermes config set` prints `✓ Set …`, the line is visibly in
  `config.yaml` — and nothing reads it, because the consumer only looks under
  one specific parent. Three "successful" writes in a row can all no-op. Also
  covers the `--` argument trap for leading-dash values, and the way a leftover
  empty parent block after `unset` can silently DISABLE a subsystem:
  `references/config-key-nesting-and-silent-noop.md`.

Heuristic: **if a change produces no error AND no visible effect, assume it was
ignored** until you have read it back out of the loaded structure.

### The writer itself can corrupt the value's TYPE

Worse than a dropped key: the official write path stores your value in the wrong
_shape_, so the reader parses it into something harmless-looking and wrong.

Verified 2026-08-15 on `hermes config set`, which takes a scalar and serializes a
list argument as a **quoted string**:

```bash
hermes config set skills.disabled '["alpha","beta","gamma"]'
# ✓ Set skills.disabled = ["alpha","beta","gamma"] in <home>/config.yaml
```

```yaml
# what actually landed — a string, not a list
skills:
  disabled: '["alpha","beta","gamma"]'
```

```python
get_disabled_skills({'skills': {'disabled': '["alpha","beta","gamma"]'}})
# -> {'["alpha","beta","gamma"]'}     ONE bogus entry; nothing is disabled
```

The CLI prints a success line. `config get` echoes the value back. The file
contains your text. And the feature is off. This is the local-tooling twin of
"readback is not proof on a third-party API" — **the writer is part of the
system under test.**

Rule: for any **list-, dict-, or otherwise non-scalar-valued** key, do not trust
a scalar-oriented setter. Write the structure with a YAML round-trip and then
re-read it through _the product's own reader function_ (not `yaml.safe_load`
alone) before believing it. On Hermes specifically, `Edit`/`Write` refuse
`config.yaml` by design, so the safe shape is a script that:

1. backs up the file (and refuses to run if the backup is missing),
2. **merges** into the existing list rather than replacing it,
3. refuses if the existing value is not already the expected type,
4. dumps to a `.tmp`, re-reads it through the real reader, aborts on mismatch,
5. only then moves `.tmp` over the original, and
6. asserts every _other_ key is byte-identical afterwards.

Steps 3 and 6 are what stop a "fix" from quietly eating unrelated config.

### Design the verification so it CAN fail

Same session, the check itself was the bug. A probe asserted on
`get_skill_commands()` assuming a **list**; the function returns a **dict** keyed
`"/name"`. The `isinstance(cmds, list)` branch silently yielded `[]`, and the
probe reported `active_in_index=0` for all five profiles — a perfect, uniform,
meaningless result that looked like a dramatic success.

Two guards, both cheap:

- **Assert the positive control.** `assert active, "empty index — probe broken"`.
  A result of "everything vanished" is far more often a broken probe than a
  working change.
- **Check both directions.** Confirm the targets are GONE _and_ that known-good
  neighbours are STILL PRESENT. Here: `comfyui` absent, and
  `multi-review`/`deep-dive`/`recall` confirmed still active.

An identical number across every profile, or a suspiciously round zero, is a
smell — inspect the probe before celebrating.

## Systemd units are a config surface too

A unit directive can be accepted, parsed, and echoed back by `systemctl show`
while doing nothing. `RequiresMountsFor=` is silently INERT in a systemd USER
unit — the user manager cannot depend on a SYSTEM mount unit, so the guard you
think protects a service does not exist. Verified by unmounting the volume and
watching the service start anyway, after `systemctl show` had confirmed the
directive and even resolved it to a real mount unit.

Read the field where a dependency must MATERIALIZE (`Requires=`), not the field
where you declared it. Then prove it by removing the dependency. Full case,
the working `ExecStartPre` guard, and sibling traps (preempted `systemctl stop`,
`XDG_RUNTIME_DIR` in non-login contexts, systemd-vs-pm2 ownership) in
`references/systemd-directives-that-silently-noop.md`.

## Readback is not proof on a third-party API

The heuristic above assumes the failure is silent _absence_. A worse shape exists
on remote APIs: the service **accepts your write, stores it, and echoes it back on
a subsequent GET** — while the field does nothing, because it is not part of the
schema the service actually consumes.

Every local check passes. `HTTP 200`. Readback shows your exact value. A diff
against intent is clean. And the feature is dead.

Live case (2026-08-06, Vapi voice assistants): the base prompt was written to
`model.systemPrompt`, a field that appears throughout third-party examples and
older docs. The API accepted it, returned it verbatim on `GET /assistant/<id>`,
and never delivered it to the model — the real field is
`model.messages[{role: "system"}]`. An assistant configured that way places a
real phone call to a real human with no persona and no task instructions. Two
sibling fields (`backchannelingEnabled`, `silenceTimeoutSeconds`) round-trip the
same way while being absent from the schema.

**Acceptance is not application, and neither is readback.** On any vendor API,
promote the machine-readable schema above prose:

```bash
# The schema the service actually validates against, not the docs page about it
curl -sS https://api.<vendor>.<tld>/api-json -o /tmp/vendor_openapi.json

# Is the field you are about to rely on real?
python3 - <<'EOF'
import json
d = json.load(open('/tmp/vendor_openapi.json'))
schemas = d['components']['schemas']
for name in ['CreateXDTO', 'UpdateXDTO', 'X']:          # the write + read DTOs
    props = set((schemas.get(name, {}).get('properties') or {}).keys())
    print(name, '->', 'systemPrompt' in props)           # the field in question
EOF
```

A field with **zero occurrences** across every relevant DTO, while the live API
happily returns it, is a ghost. Prefer the documented request/response schema and
confirm the _behavior_ on one real invocation.

Related: the vendor may also lag its own schema in the other direction — a field
present in the running service but absent from the published spec. Treat the
schema as strong evidence, not gospel; the tiebreaker is always one real call.

Full case study, audit query for finding already-damaged resources, and four
sibling traps from the same API (wrong success status on a non-idempotent create,
defaults mistaken for absence, mutually-exclusive fields, edge-level client
rejection): `references/vendor-api-phantom-fields.md`.

Docs prose, blog posts, and LLM training data all carry the deprecated field
forward long after the API moved. That is precisely why the schema check is
cheap insurance on any API you have not personally exercised.

## Source proves what IS; the tracker proves what is INTENDED

Reading the code is necessary and not sufficient. Source answers _does this
work today_. It cannot tell you whether the gap is an oversight about to be
fixed, a deliberate refusal, or a capability that exists somewhere else in the
product under another name. Answer those from the **issue tracker and the
official docs** before you design around a limitation.

Verified 2026-08-22, `delegate_task` per-task model override. Source was
unambiguous — `creds` resolves once from `delegation.*` and applies to every
child (`delegate_tool.py:3622`), and the `tasks[]` schema has no model field.
Correct, and it led to the wrong recommendation, because three things were only
discoverable outside the repo:

- **Issue #17685** — the field is _"silently accepted and discarded — no error,
  no warning."_ Known, reported, reproducible.
- **Five PRs** implemented it (#17718, #23266, #25026, #34773, #36790) and the
  maintainer closed one with **"We do not want this."** So it is a design
  position, not a backlog item — planning around its arrival is planning on
  sand.
- **The docs named the supported alternative**: _"hand the task to the kanban
  board, which does support a per-task model override."_ The capability existed
  the whole time, in a different subsystem.

The cost of skipping this: proposing an elaborate local workaround (temp homes,
copied credentials) for a problem the product already solved elsewhere, and
implicitly promising a fix that will never merge.

Cheap checks, run them before recommending an architecture:

```bash
# is the gap known, and what did maintainers decide?
gh issue list  --repo <org>/<repo> --state all --search "<feature> <symptom>"
gh pr list     --repo <org>/<repo> --state all --search "<feature>"
# read the CLOSING COMMENT on refused PRs — that is the design position
```

Then grep the docs for the feature name; a "you cannot do X here, do it via Y"
sentence is common and is the fastest path to the supported answer.

**Rule:** before saying _"the product cannot do this"_, confirm (a) no other
subsystem does it, and (b) it is not a refused proposal. A refusal is a much
stronger and more useful finding than a missing feature — it tells you to stop
asking and route around permanently.

### Match the mechanism's SHAPE to the requirement

A feature can be adjacent to your need and structurally unable to meet it.
Before offering a replacement, state what varies per unit and check the
mechanism varies that same thing.

Same session: MoA was offered as the replacement for a multi-model review
panel. Both "ask several models and combine," so it looked right. It is not —
**MoA broadcasts ONE prompt to N models**, while the requirement was **N
different prompts to N models** ("Grok, be critical" / "Claude, be
empathetic"). Per-model persona was the entire point, and MoA has no slot for
it. The user's reply was _"MoA doesn't solve my problem"_ — correctly.

Ask explicitly: _what differs between the units — the model, the prompt, the
tools, or the context?_ Then confirm the candidate mechanism parameterises that
axis. Fan-out ≠ broadcast; parallel ≠ independent.

### Prefer the product's own isolation primitive

When a mechanism needs isolation, look for the first-class unit the product
already ships before inventing one. In the same session the working answer was
an ordinary **profile** (`hermes -z ... -p reviewer`) — separate `state.db` by
design, credentials intact, nothing copied. The invented alternative
(`HERMES_HOME=$(mktemp -d)`) redirected far more than intended and returned
`HTTP 401` while exiting 0.

Tell: if the workaround requires copying credentials, seeding temp directories,
or reconstructing environment the product already assembles, there is probably
a native unit — profile, workspace, namespace, project — doing it properly.

A rule captured from a specific incident often gets generalized in the writing.
When a rule would block an otherwise-correct approach, test the rule.

Live case (2026-07-31): memory said a given model must never be reached through
a particular transport surface. Probing both surfaces showed the rule was true
for _proxied_ variants of that model, and false for the bare first-party alias,
which the router served natively either way. Both returned HTTP 200, so the
distinction was invisible without an explicit two-surface probe.

Procedure:

1. Probe both sides of the rule directly (raw request to each surface).
2. Confirm through the real application path, not just `curl`.
3. If the rule is narrower than written, **correct the memory entry in the same
   session**, preserving the case where it IS true.

Do not silently violate a standing rule because it seemed inconvenient, and do
not obey it past its evidence. Re-derive, then update.

## Appearing is not working — probe the lane too

The sandbox probe answers _does the option show up?_ It does not answer _does
the option work?_ Shipping on the first answer produces buttons that fail on
tap, which costs more trust than the ugly label you were fixing.

Whenever a probe makes an option **newly visible, renamed, or re-pointed**, add
a second probe that exercises it for real — a 1-token request on the cheapest
model is enough. Three failure modes this catches, all seen live:

- **Renaming a built-in row can break its credentials.** The exclude-plus-user-block
  trick only carries auth the block can _reach_; an OAuth/auth-store credential
  is invisible to a `key_env:` block, yielding a perfect-looking dead button.
- **HTTP 429 is overloaded.** `rate_limit_exceeded` (retry works) and
  `credit_balance_exhausted` (billing state, retry never works) share a status
  code. The absence of `x-ratelimit-*` headers is the tell.
- **One vendor can have two meters.** A healthy subscription dashboard says
  nothing about a metered API key's prepaid balance.

Also distinguish **pre-existing** breakage from breakage your edit introduced —
check whether the prior configuration used the same credential before accepting
blame or claiming a fix.

Full procedure, disambiguation tables and credential-source check:
`references/verifying-a-lane-actually-serves.md`.

## An enum of valid values is a MENU, not an implementation

The sibling of "the setting exists, but startup ignores it": the value is
_accepted, validated, and offered in the UI_ — and the dispatcher has no branch
for it, so it silently degrades to the default.

Verified 2026-08-16 on the router combo routing strategies.
`src/shared/constants/routingStrategies.ts` exports **18** strategy values, each
with a UI label and icon, including a very on-the-nose `context-optimized`
documented as "Maximize context window." The function that actually selects a
model — `src/domain/comboResolver.ts::resolveComboModel()` — implements **four**:

```ts
switch (strategy) {
  case "priority": /* first model */
  case "round-robin": /* per-combo counter */
  case "random": /* weighted */
  case "least-used": /* usage counts */
  default:
    return { model: normalized[0].model, index: 0 };
}
```

`context-optimized` falls to `default:` and returns the **first** model
unconditionally — plain `priority` under a name that promises the opposite.
Worse, the normalizer coerces any unrecognized strategy to `"priority"` too, so
a typo'd or aspirational value never errors either.

Recommending it would have shipped a config change that looked meaningful,
parsed cleanly, produced no error, and did nothing.

**Rule:** an enum member, dropdown option, or documented value is a _claim_.
Before you set it or recommend it, grep the dispatcher for a branch that
consumes it:

```bash
# does anything actually BRANCH on this value?
grep -rn "case \"<value>\"\|=== \"<value>\"\|\[\"<value>\"\]" src/ --include=*.ts
```

Zero hits outside the constants/UI/i18n files means it is decorative. Presence
in a constants list, a UI picker, or a docstring is **not** evidence of wiring —
those are the three places an unimplemented feature always still appears.

Corollary: a `default:` case that silently returns a sane-looking value is what
makes this invisible. Prefer reading the switch over trusting the enum, and be
suspicious whenever the option that perfectly solves your problem is the one
nobody documented with a code reference.

## The setting exists, but startup ignores it

A distinct and easily-missed shape: the feature is _fully built_ — type, default,
persistence, API, UI control, applier function — and still the live value is wrong,
because **startup applies the compiled-in default instead of the persisted value.**

Symptom that gives it away: **three different numbers for one setting.**

```
source default   DEFAULT_SETTINGS.optimization.cacheSize = 65536   (64 MB)
live runtime     PRAGMA cache_size                       = -16000  (16 MB)
UI fallback      parseInt(e.target.value) || 16384        (16 MB)   <-- matches live
```

When the live value matches a **fallback literal in the UI** rather than either the
declared default or a deliberate choice, someone touched the field once and the
`|| <literal>` wrote a value nobody intended. That is two bugs, not one.

Trace it as a chain and find which link reads the wrong source:

```bash
# 1. the declared default
grep -n "<settingName>" src/types/*Settings.ts

# 2. every place the underlying knob is applied
grep -rn "<pragma_or_env_name>" --include=*.ts src/ lib/

# 3. is the persisted value even stored?  (key/value or settings row)
#    "no stored row -> defaults apply" is itself a finding

# 4. WHO calls the applier, and WHEN
grep -rn "applyXSettings\|setX(" --include=*.ts src/ | grep -v "export function"
```

The failing pattern looks like this — the applier exists and is correct, but the
boot path bypasses it:

```ts
// startup: hardcoded to the DEFAULT, ignores anything persisted
db.pragma(`cache_size = -${DEFAULT_DATABASE_SETTINGS.optimization.cacheSize}`);

// the settings-aware applier is only reached from a SAVE handler
applyDatabaseOptimizationSettings(nextSettings.optimization); // settings.ts:309
```

So the configured value applies _only after someone re-saves settings_, and is lost
on every restart. **Read the boot path, not just the applier.** An applier that is
provably correct tells you nothing about which value reaches it at startup.

Related trap in the same family: a setting read from persistence but resolved to a
disabled/zero value at runtime (`mmap_size` intending 256 MB, live reporting `0`).
Same diagnosis, same fix shape.

**Reframe the work before writing code.** "Make X configurable" and "make the
configured X actually apply at startup" are different PRs. The second is smaller,
more defensible upstream, and is usually the real bug. Say so before building.

## Read the DECLARED value; never derive it from telemetry

The inverse of every trap above. Those cover a config value that fails to take
effect. This one is the opposite failure: **the declaration was correct and
readable the whole time, and it was never read** — the value got reconstructed
from output instead, and the reconstruction was wrong.

Verified 2026-08-24. A scheduled job's cadence was reported as "fires every 90
seconds" and repeated confidently three times, becoming the basis of a
remediation plan. The number came from dividing ledger rows by elapsed time.
Event ledgers write **several rows per occurrence** (`started`, `finished`,
`notified`), so rows-over-time inflates a rate by the rows-per-event factor. The
cron expression said `*/5 * * * *` — five minutes. One `grep` of the schedule
would have settled it before any analysis began.

**Rule:** if a system _declares_ a quantity somewhere — a cron expression, a
timeout, a rate limit, a pool size, a retention window — read the declaration.
A rate derived from logs is a hypothesis about the log's shape; the declaration
is the answer. Derive only when nothing declares it, and label it derived.

```bash
# read the declaration, do not infer the schedule from output
python3 -c "import json;d=json.load(open('cron/jobs.json'));
[print(j.get('name'), j.get('schedule')) for j in (d if isinstance(d,list) else d.get('jobs',[]))]"
```

### A measurement pinned to a configured limit is the limit, not the world

Sibling tell, same incident. Every timeout in that job clocked in at **exactly**
50.0s and 110.0s. Landing on a ceiling to the tenth of a second is the harness
clipping the value, not organic behavior: real durations produce a distribution,
ceilings produce a spike at the cap.

Before interpreting any measurement, check whether it equals a configured limit —
a timeout, a page size, a quota, a max-retries product. If it does, you are
reading the instrument, and the underlying quantity is unknown and larger.

### Cluster failures BY DAY before calling anything a defect

Same session: all 28 of that job's timeouts fell on a single calendar day, with
zero the day before and zero the day after. That is an **incident** in a
dependency, not a defect in the job. Grouping by day is one line and reframes the
entire diagnosis.

### Read the artifact's own comments before proposing to change it

The spec being "fixed" already carried a comment from its previous author
correctly diagnosing the behavior, naming the real remedy (a per-call deadline),
and explicitly describing the timeout as _"a backstop sized above the bounded
worst case, not the control."_ The proposed fix would have overwritten a
deliberate design decision to solve a problem that did not exist.

Config files, specs, and wrapper scripts accumulate hard-won comments. Read them
first; they are the cheapest source of intent available, and overriding one
without acknowledging it is how a fleet loses knowledge.

## Grep for references before removing anything

A config block that looks decorative may be load-bearing somewhere that fails
_silently_ rather than loudly.

```bash
grep -rn "custom:<name>\|provider: <name>\|<name>:" config.yaml cron/jobs.json
```

Surfaces worth checking in a Hermes profile: `model.provider`,
`fallback_providers[]`, `auxiliary.*`, multi-model/panel presets and their
aggregators, `delegation.*`, and every cron job definition. Panel-style configs
are the dangerous ones — a dropped slot degrades into a fluent, plausible
single-model answer with no error at all.

## Report the boundary honestly

After probing, say which layers accept the change and which do not. "Provider
rows are relabelable; individual item buttons render a raw identifier" is a
useful, actionable answer. "I'll clean up the labels" — when half of them
cannot change — is a promise that breaks on delivery.

Separate cheap reversible changes from risky wide-blast-radius ones and let the
user sequence them, rather than bundling both behind one approval.

For the naming/labeling side of this — what a surface should _say_ once you know
what can change, and why presentation should be curated per-audience while
routing stays fleet-uniform — see
`references/naming-ui-surfaces-for-non-technical-users.md`.

## Pitfalls

- **Editing the live config to find out what a key does.** Always sandbox
  first; a `.bak-<timestamp>` copy is not a substitute for not breaking it.
- **Trusting exit 0 or absence of a warning.** Read the observable output.
- **Reimplementing the logic in the probe.** Call the real function, or the
  probe validates your assumption instead of the system.
- **Stopping at the config dict for a config→env bridge.** Some levers don't act through the loaded config at all — a startup/preamble bridge copies a config key into an env var (e.g. `agent.max_turns` → `HERMES_MAX_ITERATIONS`) that the real reader consumes. Reading the loaded dict "proves" the key is set while the live behavior never changes. Exercise the bridge AND the downstream reader (e.g. call `_current_max_iterations()`, not just `load_config()`).
- **Reporting one failed lever as impossibility.** Test the matrix first.
- **Using the system interpreter.** Use the app's own; import errors masquerade
  as config errors.
- **Deleting a block because the UI stopped needing it.** Grep for references —
  panel/preset slots fail silently.
- **Leaving a disproven rule in memory.** If probing narrows a standing rule,
  correct the entry the same session or the next agent re-applies it.
- **Skipping the baseline run.** Without before/after you cannot attribute the
  change to your edit.
- **Treating a clean readback on a vendor API as proof.** A service can accept,
  store, and echo a field it never consumes. Check the machine-readable schema
  (`/api-json`, `/openapi.json`, `/swagger.json`) for the field in the write DTO
  _and_ confirm behavior on one real invocation. See "Readback is not proof on a
  third-party API."
- **Copying a field name out of docs prose, blog posts, or memory.** Deprecated
  fields outlive their removal in every non-schema source, including model
  training data. The schema is the only artifact the service validates against.
- **Assuming a wrong live value means the feature is missing.** Check whether it
  is already built and merely bypassed at startup. Proposing to "add" a setting
  that already has a UI control is an embarrassing PR; the real fix is usually a
  one-line boot-path change.
- **Comparing a local checkout against a live host without checking versions.**
  A local tree 43 releases behind (v3.8.7 vs v3.8.50) will show different
  defaults, different file layouts, and functions that moved to new modules —
  every conclusion drawn from it about production is unsound. Confirm
  `git log -1` / `package.json` version on BOTH sides before reading source to
  explain live behavior.
- **Branching a fix off a version tag instead of the deployed commit.** The
  owner's instruction was to base the fix on what was actually running in
  production, not on a version number. The version string is not the base. On
  one host the checkout HEAD was at the version the tag claimed, while the
  **running build** was a different release directory reporting the NEXT patch
  version — and that commit did not exist in the checkout at all; it lived only
  on a release branch. Resolve the deployed commit before branching:

  ```bash
  ls -la current                      # symlink -> releases/standalone-<sha>
  cat releases/<name>/BUILD_SHA       # or grep version in the standalone bundle
  curl -s localhost:PORT/api/.../health | grep version
  git branch -a --contains <sha>      # find which branch actually carries it
  git checkout -b <fix-branch> <sha>  # branch from the SHA, never the tag
  ```

  Then confirm `git rev-parse --short HEAD` equals the deployed sha before
  writing a line of code.

## Applying a verified change safely

Once a lever is proven live, editing it across many fleet configs must stay a one-line, reviewable change. ruamel.yaml will try to churn the file in ways that hide your edit:

- **Global sequence re-indent.** ruamel applies one `y.indent(sequence=…)` to the whole doc; the default turns indentless lists (`- item`) into indented (`  - item`) or vice-versa. Detect from the backup: if any line starts with ` -` use `y.indent(mapping=2, sequence=4, offset=2)`, else `y.indent(mapping=2, sequence=2, offset=0)`.
- **Folded-scalar unfolding.** Even with `width=4096`, ruamel collapses a multi-line `system_prompt` / quoted string onto one line; `y.fold_pos = 4096` does NOT preserve it.

Guard with a **diff-gate**: after dumping, the unified diff vs backup must be exactly one `-`/one `+` line containing the key (present-value case) or zero `-`/one `+` (absent-key case). If it's larger, **restore and fall back to text-surgical**: find the parent block, replace only the `  key:` value line (preserve trailing ` # comment` and EOL), rewrite, re-parse. Full implementation + readback verification: `scripts/surgical_scalar_edit.py`. Run it per profile; it backs up, gates, falls back, and asserts the value landed. See `references/safe-scalar-edit.md` for the reproduction recipe.

## A version bump is a config lever too — probe the new value before pinning

"Latest X shipped, update our setup" reads like find-and-replace. It is not. A
new version string is an unverified lever: the config will parse, the call will
return 200, and the behavior can still be worse. Newest is frequently worse on a
specific capability during launch week.

Verified 2026-08-13 (grok-4.6, one day post-release). Probing the real code path
before pinning found a **reproducible defect**: through the xAI `x_search`
Responses tool, grok-4.6 leaked raw control tokens into user-facing prose —
`<|eos|>`, and literally `show render_inline_citation with citation_id is 23` —
on **2 of 4 trials**, while the incumbent grok-4.5 was clean 4 of 4. It was also
**~4x slower** (35-64s vs 2.6-15.5s, identical prompts). Every call returned
HTTP 200. A single-probe check would have passed it 50% of the time.

**Classify each reference before editing: DORMANT vs LIVE.** The same version
string in two places has completely different blast radius. A capability
declaration under `providers.<p>.models` that nothing dispatches through is
cosmetic; a setting like `x_search.model` calls the vendor API directly. In that
session the bump shipped to the dormant catalog pin and was **withheld** from the
live execution setting — same release, opposite decisions, because each was
tested separately instead of swept. Partial application with a stated reason is a
better outcome than an all-or-nothing sweep.

**Probe requirements for a model/version swap:**

- **n≥4 trials per version**, alternating old and new on identical prompts. One
  clean trial proves nothing about an intermittent defect.
- **Assert on output content, not status.** Scan for `<|`, `|>`, and any
  tool-internal directive (`render_inline_citation`, `citation_id`) appearing in
  prose. A 200 carrying corrupted text is the actual failure mode.
- **Record per-trial latency.** Vendor or practitioner reports of "slower TTFT"
  only become actionable when measured on your own workload.
- **Use the app's own credential resolver and request shape**, not a hand-rolled
  HTTP call — import the same helper the product uses so the probe exercises the
  real path.

Reusable harness: `scripts/probe_model_release.py`. Transcript, leak samples, and
the dormant-vs-live classification worked example →
`references/model-release-regression-probe.md`.

Corollary: **rolling aliases self-update with no config change and no probe.**
`~x-ai/grok-latest` silently became 4.6 the day it shipped. When a new version
lands, check what your `-latest` pins quietly adopted — a fallback rung can take
on an untested model with nobody editing anything.

### After the upgrade lands: auditing what you got

The mirror question — _"we're several releases ahead now, what should we enable,
what silently got better?"_ — is the same discipline pointed backwards. Anchor on
the deployed BUILD pair (not the version string, which can be identical across
hundreds of commits), grade every candidate feature against your own call
telemetry rather than its commit message, read the failure path before adopting a
resilience feature, and **verify the subsystem is actually running before
crediting a fix** — a "fixes 0% hit rate" commit is worthless against a cache
that stopped writing twelve days earlier. Includes the matched-baseline
measurement shape and the rule against crediting a change that had not yet run:
`references/post-upgrade-capability-audit.md`.

## The edit list in a work order is rarely the whole inventory

A change order naming "profiles X, Y, Z" is a starting point, not a census.
Verified 2026-08-13: the order named three profiles; a filesystem sweep found the
pin in **four**. Enumerate from disk before editing, excluding backup and test
trees so the count is honest:

```bash
cd ~/.hermes/profiles
for d in */config.yaml; do
  case "$d" in *opus5-ab*|*backups*|*home/.hermes*) continue;; esac
  grep -nE '<pattern>' "$d" && echo "  ^ $d"
done
```

Report the discrepancy — the requester's model of the fleet is stale, and that is
useful to them.

**Hermes refuses agent writes to its own profile's `config.yaml`**, returning
`Refusing to write to Hermes config file … Agent cannot modify security-sensitive
configuration`. That is the self-config guard working as designed, not a broken
tool. A fleet-wide edit that includes the profile you are running as completes
N-1 automatically; name the remaining manual step (`hermes config` or a hand
edit) instead of reporting the batch as done.

## A steward's authorization does not lift the principal's freeze

When a delegated work order says a class of change is "routine and yours," that
grants autonomy from the _steward's_ side only. If the principal has a standing
constraint covering the same action, the steward cannot clear it — escalate and
hold. Verified 2026-08-13: a work order declared version bumps routine while a
standing freeze on `config.yaml` edits was in force; the correct move was to
stage the change fully, report it ready, and wait for the principal. Executing on
the steward's authority alone would have silently overridden the person who set
the constraint.

## Merged is not deployed

The same disease one layer out: a change that lands in the repo, reports success at every
checkpoint, and is not running. A merged PR left a feature **inert on the host** because
the deploy mirrored one file while the component had grown two sibling modules it
imported defensively — 420 clean runs, no errors, feature absent. Separately, `git push
-q` exited 0 having pushed nothing.

Before reporting anything delivered, name the layer your evidence comes from and ask
whether that layer can observe the claim. Exit code is not work product; file presence is
not runtime state; merge status is not deployed behavior. **Ask the component that
consumes the thing to report its own state.**

See `references/merged-is-not-deployed.md` for the five measured cases, the
dependency-growth trap that silently invalidates every mirror naming the old filename,
and the evidence table.

## Verification Checklist

- [ ] Change probed in a throwaway home, not the live config
- [ ] Real code path exercised with the application's own interpreter
- [ ] Baseline (unmutated) run captured for comparison
- [ ] Effect confirmed in observable output, not exit code
- [ ] For any non-scalar key: value re-read through the PRODUCT's reader and
      confirmed to be the right TYPE, not just present (a scalar setter can
      store a list as a quoted string and report success)
- [ ] Verification has a positive control — it fails when nothing changed, and
      known-good neighbours are asserted STILL present, not only targets absent
- [ ] On a vendor API: field confirmed present in the machine-readable schema's
      write DTO, not just accepted and echoed back on a GET
- [ ] Full lever matrix tested before claiming something is impossible
- [ ] Before declaring a capability missing: issue tracker AND official docs
      searched — a refused PR ("we do not want this") or a
      "do it via <other subsystem>" doc line changes the recommendation
- [ ] Replacement mechanism checked for SHAPE, not just category — it varies
      the same axis the requirement varies (prompt? model? tools?)
- [ ] Native isolation primitive (profile/workspace/namespace) ruled out before
      inventing one with temp dirs or copied credentials
- [ ] Every removed block grepped for references first
- [ ] Any standing rule that was narrowed is corrected in memory
- [ ] Any quantity a system DECLARES (schedule, timeout, quota, pool size) was
      read from the declaration, not derived from log rows or telemetry
- [ ] Any measurement sitting exactly on a configured limit treated as the
      instrument clipping, not as data about the world
- [ ] Failures clustered BY DAY before being called a defect
- [ ] The target artifact's own comments read before proposing to change it
- [ ] Boundary of what is/isn't changeable reported honestly
- [ ] Any push/merge/deploy whose success is about to be reported was confirmed
      at the destination (remote SHA, running component's own version) — never
      from a `-q` exit code
- [ ] Any component that grew a dependency: every mirror, deploy, drift check
      and validation path naming the ORIGINAL filename re-checked, since each
      becomes incomplete silently
- [ ] Any new persistent store added to a component was added to the test
      isolation list, or fixtures will write into production state
- [ ] On a version/model bump: every reference enumerated from disk (not from
      the work order), each classified DORMANT vs LIVE before editing
- [ ] On a version/model bump: n≥4 alternating trials on the real path, output
      text scanned for control-token leakage, latency recorded per trial
- [ ] Rolling `-latest` aliases checked for what they silently adopted
- [ ] Any site left unbumped is named, with the evidence for holding it
