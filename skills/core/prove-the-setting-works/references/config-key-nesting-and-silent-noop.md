# Config key nesting: right key, wrong level, silent no-op

## Trigger

Use when setting a per-platform / per-subsystem config key in Hermes and the
behavior does not change — especially when `hermes config set` printed a
success line and the value is visibly present in `config.yaml`.

Companion to the main skill's "Config shapes that look right and silently
no-op." This is the _nesting-level_ variant: the key name is correct, the value
is correct, and it is parked at a level nothing reads.

## The failure, verified live (2026-08-19)

Goal: stop a gateway from replying to unknown iMessage senders with pairing
codes. Correct key, three attempts, all "successful", none effective:

```bash
# attempt 1 — top level
hermes config set -- bluebubbles.unauthorized_dm_behavior ignore
# ✓ Set bluebubbles.unauthorized_dm_behavior = ignore in .../config.yaml

# attempt 2 — under gateway:
hermes config set -- gateway.bluebubbles.unauthorized_dm_behavior ignore
# ⚠ not a recognized config key — saved anyway

# attempt 3 — under gateway: with extra:
hermes config set --force -- gateway.bluebubbles.extra.unauthorized_dm_behavior ignore
# ✓ Set ... in .../config.yaml
```

After each, the resolver still returned `pair`:

```
bb extra: None
RESOLVED bluebubbles: pair
```

The reader only consumes `PlatformConfig` objects built from
`gateway.platforms.<name>` (`GatewayConfig.from_dict`, `gateway/config.py`
~1137-1146). Anything at another level parses, persists, echoes back, and is
never read.

## Diagnosis: read the RESOLVED value, never the file

Grepping YAML proves the text landed. It does not prove anything consumes it.
Call the product's own resolver:

```python
import os
os.environ["HERMES_HOME"] = os.path.expanduser("~/.hermes")
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"), override=True)   # env can outrank the file

mod = __import__("gateway.run", fromlist=["x"])
gc  = __import__("gateway.config", fromlist=["GatewayConfig"])
from gateway.session import Platform

raw = getattr(mod, "_load_" + "gateway" + "_config")()   # returns a dict
cfg = gc.GatewayConfig.from_dict(raw)                    # NOT .from_env()
print(cfg.platforms.get(Platform.BLUEBUBBLES))           # None => nothing read it
```

Two traps inside the probe itself, both hit live:

- `_load_gateway_config()` returns a **plain dict**, not a `GatewayConfig`.
  `.platforms` on it raises `AttributeError`. Wrap with `.from_dict()`.
- `GatewayConfig.from_env()` **does not exist**. The constructor is
  `from_dict`.

For a top-level block (e.g. `telegram:`) that the loader bridges into `extra`,
rebuild it the way the loader does before instantiating an adapter:

```python
tg  = dict(raw.get("telegram") or {})
ext = dict(tg.pop("extra", {}) or {})
for k, v in tg.items():
    ext.setdefault(k, v)          # loader folds siblings into extra
tg["extra"] = ext
pcfg = gc.PlatformConfig.from_dict(tg)
```

## `hermes config set` argument traps

- **Leading-dash values need `--`.** A Telegram chat id such as
  `-1001234567890` is parsed as a flag; argparse prints the CLI usage text and
  exits. Use `hermes config set -- <key> <value>`.
- **`key=value` is not supported.** Key and value are separate positionals.
- **The `⚠ not a recognized config key` notice is a real signal.** It means the
  running version has no schema entry at that path. The value is still written.
  Treat the warning as "this will not be read," not as cosmetic noise.

## An empty leftover section can DISABLE a subsystem

The most expensive part of the incident. After unsetting the keys, this
remained:

```yaml
gateway:
  platforms:
    bluebubbles:
      enabled: false
```

`hermes config unset` removed the leaves and left the parent. That residue is a
valid explicit `enabled: false`, and the platform silently stopped loading —
`Gateway running with 1 platform(s)` instead of 2. The subsystem was off for
reasons unrelated to the original goal, caused by the cleanup rather than the
change.

**After any unset, re-read the parent block and delete an orphaned section.**
Then confirm the platform count in the startup log:

```bash
grep -E "Gateway running with|✓ .* connected" gateway.log | tail -3
```

## Prefer a lever whose default does the work

Before inventing an explicit key, check whether an existing signal already
flips the default in the direction you want. Here,
`_get_unauthorized_dm_behavior` (`gateway/authz_mixin.py` ~797-900) falls back
to `"ignore"` whenever **any** allowlist is configured for the platform:

```bash
# one .env line replaced three failed config attempts
BLUEBUBBLES_ALLOWED_USERS=+15551234567
```

That both authorized the intended user and flipped unauthorized-DM behavior to
`ignore` — verified through the resolver, not inferred. Reading the resolution
order first would have skipped the whole detour.

## Credentials are not an on-switch (but one platform treated them as one)

Worth checking when a platform is live that you never enabled: in this Hermes
version `gateway/config.py` assigned `enabled = True` directly for BlueBubbles
whenever a server URL and password were present, bypassing `_enable_from_env`
and ignoring an explicit `enabled: false`. Having send credentials forced the
inbound listener on.

Generalize: when a platform is unexpectedly listening, grep its enable path for
a direct `.enabled = True` assignment rather than assuming config governs it.

## Pitfalls

- Grepping `config.yaml` to confirm a setting took effect. It confirms text,
  not consumption.
- Trusting `✓ Set ...` output. The writer succeeded; the reader was never
  consulted.
- Forgetting `.env` overrides. Load dotenv in the probe or the resolved value
  will not match the live process.
- Restarting to "make it take effect" without first proving the resolver
  returns the new value — a restart cannot fix a key nothing reads, and the
  restart makes it look like it should have.
- Leaving an orphaned parent block after `unset`.

## Checklist

- [ ] Resolved value read through the product's own resolver, not the YAML
- [ ] `.env` loaded in the probe (env commonly outranks the file)
- [ ] `GatewayConfig.from_dict(raw)` used, not `.from_env()`
- [ ] Existing default-flipping levers (allowlists) checked before adding a key
- [ ] After `unset`: parent block checked for an orphaned, behavior-changing stub
- [ ] Post-restart: subsystem/platform count confirmed in the startup log
