# Adopting third-party CODE (vendor a plugin / fork a repo / "make it ours")

The parent skill's rules assume a **vendor service** you call over an API.
Adopting someone's **open-source code** into your tree is the sibling class, and
it has different, harder blockers. Triggers: _"can we put this into our repo?"_,
_"copy it over and make it ours"_, _"this feels like a worthwhile plugin"_,
_"we want to keep tweaking it ourselves"_.

Grounded in the `hermes-progress-tail` evaluation, where the
adoption question looked like a policy debate and was actually settled by two
facts nobody had checked.

## Check order — hard blockers before soft ones

Answer in this sequence. Stop at the first hard NO.

| #   | Check                                             | Why it outranks the rest               |
| --- | ------------------------------------------------- | -------------------------------------- |
| 1   | **License**                                       | Legal. Not ours to decide.             |
| 2   | **Runtime compatibility** across the target fleet | Physics. Blocks adoption in any form.  |
| 3   | **Coupling surface** (LOC + private-API reach)    | The real recurring cost.               |
| 4   | Our own repo charter / conventions                | A preference we wrote and can rewrite. |

🔴 **Lead with 1–3, not 4.** In the real session I answered "no" primarily from
our repo's own charter ("this is a seed, not an upstream"). The operator pushed
back correctly — charter is a preference, and preferences lose to a genuinely
good idea. The actual blockers were legal and structural, and I had not checked
either. **A policy answer to a technical question reads as bureaucracy and
invites a re-litigation you deserve to lose.**

## 1 — License FIRST, and never assume one exists

```bash
gh api repos/<owner>/<repo> --jq '.license.spdx_id'   # null == no license
ls LICENSE* COPYING* 2>/dev/null                       # confirm in-tree too
```

`hermes-progress-tail`: **`license: null`, no LICENSE file.** 277 commits, 11
stars, active pushes, an installer and an uninstaller — every social signal of an
open project, and **no grant of rights**. Under default copyright that means no
right to copy, modify, or redistribute.

Consequences worth stating plainly to the operator:

- Vendoring unlicensed code into **our public MIT repo** would publish someone
  else's work under a license they never granted.
- This is not a taste call or a charter call. It is not ours to make.
- It is usually **fixable with one polite ask** — most authors simply never
  added a license file. Offer to open that issue.
- Meanwhile **using it unmodified via the author's own installer is fine**;
  it is _copying into our tree_ that the missing license blocks.

Ideas are not copyrightable. If we ultimately want the behavior, reimplementing
from the _concept_ is legitimate; copying the _expression_ is not.

## 2 — Runtime floor vs. the actual fleet

Read the declared floor from the source of truth, then measure every host. Do
not reason from "we're modern, it's probably fine."

```bash
grep -E 'requires-python|python_requires' pyproject.toml setup.py 2>/dev/null
# then, per host:
for h in <hosts>; do printf "%-9s " $h;
  ssh $h '~/.hermes/hermes-agent/venv/bin/python -V 2>&1' | tail -1; done
```

Measured result: plugin required `>=3.12`; five of six fleet hosts ran 3.11.x and
one had no venv at all. **One host qualified.** That reframes "should we adopt
this?" into "we cannot run this," which is a much cheaper conversation — and it
belongs _before_ any repo-hosting debate.

## 3 — Size the coupling surface, don't eyeball it

"Copy it over and we'll tweak it" prices the copy and ignores the maintenance.
Measure three numbers:

```bash
# a. total volume
find <pkg> -name '*.py' | wc -l
find <pkg> -name '*.py' -exec wc -l {} + | tail -1

# b. private-API reach into the fast-moving host project
grep -rhn "^\s*from \(agent\|tools\|gateway\|hermes_c\)[a-z_.]* import.*" <pkg>/ \
  | sed 's/^[0-9]*://;s/^ *//' | sort -u

# c. monkeypatch families (the real breakage count)
grep -c "def install_" <pkg>/hooks/*.py | grep -v ':0'
```

`hermes-progress-tail` measured **16,169 lines / 86 files**, importing **13
distinct private symbols** (`gateway.run.GatewayRunner`,
`gateway.platforms.base.BasePlatformAdapter`, `tools.delegate_tool`,
`agent.model_metadata.*`, …) and installing **13 monkeypatch families** across 7
modules.

Then ask the decisive question: **how fast does the host project change those
exact files?** Upstream merges ~1,400 PRs per release; `gateway/run.py` alone is
~30k lines and changed twice during the session. Every private symbol and every
patch point is a silent-breakage site on each upgrade.

Ratio test worth saying out loud: **16k lines of permanent maintenance surface
to fix a problem whose upstream fix is ~15 lines.** State the ratio; it usually
ends the debate without needing a policy argument.

## 4 — Look for the sanctioned extension point

Before concluding "it must monkeypatch," check whether the host project has a
real plugin/hook API and how much of it the candidate actually uses.

```bash
ls <host-project>/gateway/hooks.py <host-project>/gateway/builtin_hooks
```

Hermes ships an event-driven hook API (`HOOK.yaml` + `handler.py`). The plugin
used almost none of it — because the API does not expose what it needed. **That
gap is the actionable finding**: the durable contribution is widening the hook
API upstream, not adopting 16k lines of reverse-engineered patches.

## Separate the CAPABILITY from the ARTIFACT

The operator's real goal is nearly always the capability, not the specific repo.
Say the distinction back to them explicitly:

- _"Control over message flow"_ → belongs upstream in the config/mechanism that
  already exists; small diffs, survives every upgrade, zero maintenance.
- _"A rich live-HUD renderer"_ → what the artifact actually is; large, coupled,
  and only worth it if the UX win is proven.

Splitting these let the real session end with the right call in one message
instead of an ownership argument.

## Recommended sequencing when the idea still has merit

1. **Ask the author for a license.** One issue comment; unblocks everything.
2. **Trial it UNMODIFIED**, via the author's installer and update path, on the
   one host that qualifies. Prove the UX is better _before_ debating ownership.
3. **Keep the upstream fix moving** — the durable lever.
4. **Only if the trial wins and we still need control**: write a smaller plugin
   against the sanctioned hook API, borrowing ideas (not expression), and
   contribute hook-API gaps upstream.

## Pitfalls

- **Treating "no license" as pedantry.** It is the whole answer to "can we make
  it ours." Check it in the first minute, not after a design.
- **Social signals read as permission.** Stars, an installer, active commits, and
  a friendly README grant no rights.
- **Pricing the copy instead of the coupling.** The copy is free; the upgrades
  are forever, on a fleet, with the operator paged when delivery breaks.
- **Leading with your own repo's charter.** It is the weakest argument in the
  stack and the easiest to overturn. Use it last, if at all.
- **Assuming the maintenance falls on the author.** The moment it is vendored,
  every silent break is ours, on our upgrade schedule.
- **Forgetting the reversible middle path.** "Use it unmodified from upstream"
  is almost always available and needs no ownership decision at all.
