# Model-release regression probe — grok-4.6, one occasion

Worked case behind "a version bump is a config lever too." A one-day-old release
was ordered pinned everywhere; probing first found a reproducible output defect
and a 4x latency regression. Part of the bump shipped, part was withheld.

## The ask

"Latest grok just came out (4.6). Update our setup accordingly." A prior work
order from the model-config steward had specified the exact edit: bump the
OpenRouter pin from `x-ai/grok-4.3` to `x-ai/grok-4.6`, correct `context_length`
from 1000000 to 500000, roll to every profile that has it.

Read literally that is find-and-replace. It was not.

## Step 1 — enumerate, don't trust the list

The order named three profiles. A filesystem sweep found four.

```bash
cd ~/.hermes/profiles
for d in */config.yaml; do
  case "$d" in *opus5-ab*|*backups*|*home/.hermes*) continue;; esac
  grep -nE 'grok' "$d"
done
```

```
a monitoring agent     38: grok:            50: x-ai/grok-4.3    614: x_search model: grok-4.5   652: moa model: grok
the operations agent     38: grok:            53: x-ai/grok-4.3    686: x_search model: grok-4.5   730: moa model: grok
a personal-assistant agent      38: grok:            50: x-ai/grok-4.3    642: x_search model: grok-4.5   703: moa model: grok
a research agent  38: grok:            50: x-ai/grok-4.3    673: x_search model: grok-4.5   455: moa model: grok
```

Excluding `opus5-ab/`, `backups/`, and `home/.hermes/` matters — those trees held
dozens of stale copies that would have inflated the count and produced a
misleading report.

## Step 2 — classify DORMANT vs LIVE

Four distinct references, three different blast radii:

| reference                                          | what it is              | dispatches traffic?            |
| -------------------------------------------------- | ----------------------- | ------------------------------ |
| `providers.the router.models.grok`                 | combo alias declaration | via combo, version-free        |
| `providers.openrouter-direct.models.x-ai/grok-4.3` | capability declaration  | **no** — nothing routes to it  |
| `x_search.model: grok-4.5`                         | tool execution setting  | **yes** — direct to `api.x.ai` |
| `moa[].reference_models[].model: grok`             | combo alias leg         | via combo, version-free        |

Confirming the catalog pin is dormant: no agent default, no aux slot, no combo,
no cron references it. Confirming `x_search` is live — the tool reads config and
calls the vendor directly, bypassing the router entirely:

```python
# tools/x_search_tool.py
def _get_x_search_model() -> str:
    cfg = _load_x_search_config()          # load_config().get("x_search", {})
    return (str(cfg.get("model") or "").strip() or DEFAULT_X_SEARCH_MODEL)
# ... POSTs to {base_url}/responses with tools=[{"type": "x_search"}]
```

The two combo-alias references need no edit at all — they name `grok`, not a
version, and follow router rung 1.

## Step 3 — probe the live path before touching it

Import the app's own credential resolver so the probe exercises the real path:

```python
sys.path.insert(0, "~/.hermes/hermes-agent")
from tools.xai_http import resolve_xai_http_credentials
```

Run with the app's interpreter (`./venv/bin/python`) — system python3 lacks the
package and its ImportError looks like a config problem.

### Result — 4 trials per model, alternating, identical prompts

```
########## grok-4.6
  q1 t1   39.5s  LEAK ['render_inline_citation', 'citation_id is']
      xAI's newest Grok model is Grok 4.6. show render_inline_citation with citation_id is 23
  q1 t2   64.2s  clean
  q2 t1   50.6s  LEAK ['render_inline_citation', 'citation_id is']
  q2 t2   35.8s  clean

########## grok-4.5
  q1 t1    2.6s  clean
  q1 t2   10.0s  clean
  q2 t1   15.5s  clean
  q2 t2   13.1s  clean
```

An earlier single probe had also produced a bare `<|eos|>` in the output text.

Two findings, both invisible to a status check:

1. **Control-token leakage, 2/4 on the candidate, 0/4 on the incumbent.** Every
   call returned HTTP 200. An agent consuming this gets corrupted search results
   roughly half the time with nothing to catch.
2. **~4x slower** — 35-64s vs 2.6-15.5s on identical queries. This matched a
   practitioner TTFT caveat that had been relayed second-hand; the probe turned
   a report into a measurement.

`n=4` is small. Report it as suggestive, not conclusive — but 2/4 vs 0/4 with a
clean mechanism (tool-directive text escaping into prose) is enough to hold.

## Step 4 — ship the safe subset, hold the rest

- **Applied** to the dormant catalog pin in 3 profiles (`x-ai/grok-4.6`,
  `context_length: 500000`).
- **Withheld** on `x_search.model` in all 4 — left at `grok-4.5`.
- **Untouched**: the two combo-alias legs, which carry no version.
- **Blocked by design**: the 4th profile is the one the agent runs as. Hermes
  returned `Refusing to write to Hermes config file … Agent cannot modify
security-sensitive configuration`. Correct guard behavior; needs `hermes config`
  or a hand edit.

Same release, same week, opposite decisions per site — only possible because each
site was classified and tested separately instead of swept.

## Step 5 — verify the three layers separately

```
LAYER 1  parse    a personal-assistant agent/a monitoring agent/a research agent PARSE OK  grok_pin=x-ai/grok-4.6  ctx=500000
LAYER 2  resolve  openrouter/x-ai/grok-4.6 -> provider openrouter, model x-ai/grok-4.6, 200
LAYER 3  call     real payload returned, no error, no fallback
```

Layer 1 via the app's interpreter reading the _loaded dict_, not the file text.
Layer 2 and 3 read the router's own `call_logs` metadata (`provider`, `model`,
`requested_model`, `status`) rather than the model's self-description.

Running layer 2 against the _proposed_ target also surfaced something the order
had wrong: it compared 4.6's pricing to 4.5 and found parity, but the pin being
replaced was 4.3. Against the actual incumbent it is **2.4x the output cost at
half the context** ($1.25/$2.50 at 1M → $2.00/$6.00 at 500K). Immaterial while
dormant; material the moment anything routes through it. Compare against what is
actually installed, not against the previous release.

## Transferable rules

- A new version string is an unverified lever. Probe before pinning.
- Classify every reference DORMANT vs LIVE first; blast radius differs per site.
- n≥4 alternating trials. Intermittent defects pass single probes.
- Assert on output text (`<|`, `|>`, tool directives), not HTTP status.
- Rolling `-latest` aliases adopt the new release with no edit and no probe —
  check what they silently became.
- Partial application with a stated reason beats an all-or-nothing sweep.
