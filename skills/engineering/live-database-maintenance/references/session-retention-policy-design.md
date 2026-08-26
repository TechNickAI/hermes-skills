# Designing a session retention policy (archive vs prune) across a fleet

Use this when the ask is **"set up the ideal session-management config"** rather
than "run maintenance on this one database." The lever here is the `sessions:`
config block, not a stop-mutate-start sequence — but the sizing discipline from
the parent skill still governs, and it is what stops you shipping a policy that
reclaims nothing.

## The `sessions:` config block (read from installed source)

Everything lives under a top-level `sessions:` key in `config.yaml`
(`hermes_cli/config_defaults.py`, the block opening at the comment
"Session storage — controls automatic cleanup of ~/.hermes/state.db"). Read that
block directly rather than trusting docs; it carries the rationale for each
default inline.

| key                                           | default    | what it does                                  |
| --------------------------------------------- | ---------- | --------------------------------------------- |
| `auto_prune`                                  | `false`    | DELETE ended sessions idle > `retention_days` |
| `retention_days`                              | `90`       | idle-days kept by prune                       |
| `auto_archive`                                | `false`    | soft-hide sessions idle > `auto_archive_days` |
| `auto_archive_days`                           | `3`        | idle threshold for archive                    |
| `vacuum_after_prune`                          | `true`     | VACUUM only when prune deleted >= 1 session   |
| `min_vacuum_interval_days`                    | `30`       | floor between VACUUM rewrites                 |
| `min_interval_hours`                          | `24`       | floor between auto-maintenance sweeps         |
| `write_json_snapshots`                        | `false`    | legacy per-session JSON writer                |
| `fts_optimize_notice`                         | `"advise"` | nag about the v23 index layout                |
| `max_resume_messages` / `max_export_messages` | `20000`    | runaway-session guards                        |

Rule zero from `hermes-config-source-audit` applies: absent from the file means
active at default, not off.

The sweeps are invoked from `cli.py` (`_run_state_db_auto_maintenance`),
`gateway/run.py`, and the web server's ticker — so a gateway-only host still
runs them.

## Measured: archive preserves search, prune destroys it

Do not reason about this from the code; it is cheap to prove. Script at
`scripts/verify_archive_vs_prune.py` in this skill. Measured result:

```
search hits BEFORE archive: 1
search hits AFTER  archive: 1     <- archive does NOT hide from search
archived flag in DB: 1
list include_archived=False: 0    <- but it IS hidden from /resume + sidebar
list include_archived=True: 1
search hits AFTER prune: 0 <- prune is unrecoverable
```

Mechanism: `search_messages()` in `hermes_state_search.py` filters only on the
MESSAGE columns `active` / `compacted`. It never joins against
`sessions.archived`. Archiving is purely a listing-layer soft-hide.
`archive_stale_sessions()` archives whole compression lineages, exempts
`pinned`, and skips `end_reason='compression'` roots, so it cannot resurrect or
orphan a live conversation.

**Therefore the default answer to "archive or delete?" is archive.** It buys the
entire UX win (a clean `/resume` list) at zero recall cost and is reversible.
Prune is the only irreversible one and should stay opt-in per host with a
stated reason.

Two gotchas when writing the proof script:

- `prune_sessions()` only considers **ended** sessions. A test session you never
  ended will survive prune and make the destructive case look non-destructive.
  Call `end_session(sid, "completed")` (the `end_reason` arg is required).
- The constructor takes a `Path`, not a `str`, and the writer is
  `append_message()`, not `add_message()`.

## Size the problem before choosing `retention_days`

The instinct is "turn on prune at 90 days." Measure first — the number is
usually near-zero, because agent-fleet bloat is **recent volume**, not old
history.

Measured across 14 profiles / 8 hosts (~23 GB of `state.db`): sessions idle
more than 90 days were 390 on one profile, 271 on another, 3 on a third, and
**0 everywhere else**. A 90-day prune would have destroyed history fleet-wide
and freed essentially nothing.

Where the volume actually was, by `sessions.source`:

| profile                    | dominant source        |
| -------------------------- | ---------------------- |
| studio `_root`             | cron 95% of messages   |
| a personal-assistant agent | cron 72%, subagent 15% |
| the operations agent       | cron 50%, telegram 40% |
| a research agent           | telegram 70%, cron 17% |

So the real lever on an agent fleet is **source-class retention** (cron and
subagent chatter aged out on their own clock) rather than a blanket age cutoff.
Machine chatter is also the audit trail when a scheduled job misbehaves, so
propose a longer cron window and confirm the auto-sweep actually supports a
source filter before promising it — the CLI `sessions prune` takes `--source`,
but the config-driven `maybe_auto_prune_and_vacuum` path may not expose one.
Verify rather than assume; see `fleet-session-store-maintenance.md`.

## Check the FTS layout before promising a reclaim

The parent skill's sizing section shows the trigram index routinely rivals or
exceeds the message text. Before recommending `hermes sessions optimize-storage`
for its advertised ~60%, confirm the DB is not **already** on the optimized v23
external-content layout:

```sql
select value from state_meta where key='fts_storage_version';   -- 1 = v23
select sql from sqlite_master where name='messages_fts';        -- 'content=' = external
```

Measured: 13 of 14 fleet profiles already reported `fts_storage_version=1` with
external content, so that reclaim was already banked and there was no win to
offer. Two profiles legitimately read `None` (a tiny/fresh DB and one still on
the legacy inline layout) — a `None` is worth a look, not an alarm.

## VACUUM is not free on a multi-GB store

`vacuum_after_prune` defaults true and only fires when prune actually deleted
rows. Under an archive-only policy nothing is deleted, so nothing is reclaimed
and VACUUM never runs — that is correct, not a misconfiguration. Do not enable
prune purely to trigger a VACUUM on a 6+ GB database; it blocks writes for
seconds per 100 MB.

## Auditing the fleet

Drive the sweep with `ssh host 'bash -s' < script` (zsh aborts the whole command
on an unmatched `~/.hermes/profiles/*/` glob), prefer
`~/.hermes/hermes-agent/venv/bin/python` (macOS fleet hosts have no system
PyYAML), and open every DB `file:{db}?mode=ro`. Iterate the root `$HERMES_HOME`
**plus** each named profile directory; reading a profile's own `config.yaml` off
disk is required, because a bare CLI call resolves to the host default profile
and will report the wrong profile's settings.

Report per profile: file size, session count, archived count, message count,
count idle beyond the candidate retention window, and the `sessions:` block as
found. The idle-count column is the one that kills or justifies the whole
proposal, so put it in the first table you show.

## Pitfalls

- **Recommending `retention_days` without counting idle sessions first.** The
  count is usually 0 and the recommendation is then pure downside.
- **Assuming archive hurts recall.** It does not; prove it and say so plainly,
  because the user's instinct that archiving is safer than deleting is correct
  and deserves confirmation rather than hedging.
- **Treating `auto_archive_days: 3` as usable.** The default is aggressive for a
  human working across several threads; 14 days keeps the sidebar clean without
  hiding work still in flight.
- **Missing the one host that is out of policy.** Diff the block across every
  profile. One host had `auto_prune: True` while all 13 others were `false` —
  silently deleting history under a fleet policy that said not to.
- **Promising the `optimize-storage` reclaim before checking
  `fts_storage_version`.** It is often already applied.
