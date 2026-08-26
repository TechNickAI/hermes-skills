# Runtime settings are not all config keys — and your probe may not be the consumer

Companion to the sandbox-probe method. Two adjacent traps, both measured
2026-08-22 while auditing a Hermes `state.db`.

---

## 1. Read the setting from the CONSUMER, not from a convenient handle

The sandbox probe insists on running the _real code path_. The same discipline
applies to _reading_ a value — and it is easy to forget when the value looks
like it lives on the artifact rather than on the process.

SQLite pragmas are the clean example. These are **per-connection**, established
by whatever code opened the handle:

`journal_size_limit` · `busy_timeout` · `cache_size` · `synchronous` ·
`locking_mode` · `temp_store`

These are **persistent properties of the file**:

`journal_mode` · `page_size` · `auto_vacuum` · `application_id` · `user_version`

Reading a per-connection pragma from a throwaway diagnostic connection returns
_that connection's defaults_. It is not a measurement of the running service. I
read `journal_size_limit` as `-1` (unlimited) and reported a disk-fill risk; the
application had set it to 64 MiB at connect time, and the live WAL capped at
exactly `67108864` bytes.

**Generalization beyond SQLite:** any setting applied at process start —
`ulimit`, `GOMAXPROCS`, JVM flags, an env var read once into a module global,
a client timeout configured in code — cannot be observed from a sibling process.
Ask _who applies this, and when_. If the answer is "the app, at startup," then
the sources of truth are the app's source and the app's observable artifacts,
not a fresh handle.

**Falsifiers, in order of strength:**

1. **Watch the artifact.** A value pinning at a round number that matches a
   source constant is proof the setting is live.
2. **Grep the source** for the setting name. If the app sets it, your reading is
   irrelevant.
3. **Inspect the live process** — `/proc/<pid>/fd`, `/proc/<pid>/limits`,
   `lsof -p <pid>`.

---

## 2. Ask whether the lever exists before designing around its absence

Before proposing a config-only fix, confirm a config key actually governs the
behavior. Grep the codebase for the key namespace and see what is really there:

```bash
grep -rn 'database\.get(\|"database"\]\.' <src> --include=*.py | grep -v test
```

In this case the entire `database.*` namespace exposed exactly one key
(`journal_mode`). The expensive FTS trigram index — 40% of the file — had no
config gate and no env gate at all. Knowing that _before_ drafting a plan turns
"disable it in config" into an honest "this requires a code change," which is a
different conversation with a different cost.

**The inverse trap, equally important:** absence of a config key does not mean
absence of a mechanism. Before concluding "there is no lever," also check for an
_existing operational mechanism that is switched off_:

```bash
grep -i 'prune\|vacuum\|retention\|hygiene\|cleanup' <profile>/cron/jobs.json
```

This session found a purpose-built weekly pruner sitting `enabled: false`,
paused during the previous day's incident and never restored. The lever existed
and was well-designed; it had simply been turned off. Re-enabling beats writing
a replacement, because the existing job already encodes headroom guards and
scope limits a fresh script will omit.

---

## 3. A DDL guard is not an off switch

When evaluating whether an object can be removed "permanently," read the
creation path for whether it is **idempotently re-applied on every startup**.

```python
cursor.executescript(ddl)   # runs even when the table already exists
```

with DDL of the form `CREATE VIRTUAL TABLE IF NOT EXISTS ...` means a manual
`DROP` survives exactly until the next restart, then silently rebuilds — and you
pay the full rebuild cost for nothing. `IF NOT EXISTS` reads like a guard
against clobbering; here it is the mechanism that _undoes_ your change.

Say "this needs a code change to persist" rather than shipping a DROP that
reverts on restart. Check the same way for any object you plan to remove out of
band: indexes, triggers, views, materialized tables.

---

## Checklist additions

- [ ] Setting classified as per-connection/per-process vs persistent-on-artifact
      before its value is reported
- [ ] Per-process settings verified via app source + live artifact, never via a
      sibling handle
- [ ] Config namespace grepped to confirm the lever exists before proposing it
- [ ] Existing-but-disabled mechanisms checked before concluding "no lever"
- [ ] Any out-of-band DROP/removal checked against an idempotent startup DDL path
