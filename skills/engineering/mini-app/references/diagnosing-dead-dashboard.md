# Diagnosing a "dead" mini-app dashboard

A checklist for the case where a dashboard looks broken or stale. Two distinct failure classes that get confused, plus the write-completeness trap.

## 1. "PM2 says nothing is running" — almost always the $HOME trap

When pm2 runs inside an agent/tool shell, `$HOME` is rewritten to the profile home, so `pm2 list` reads the wrong `PM2_HOME` and may even spawn a phantom second daemon. The real app is still up under `/Users/<user>/.pm2`.

```bash
# Confirm the real registry, not a mis-homed view:
export PM2_HOME=/Users/<user>/.pm2   # literal path, never ~ or $HOME
pm2 list

# Independent proof the app is actually alive (trust this over pm2 list):
lsof -nP -iTCP:<port> -sTCP:LISTEN
curl -s http://127.0.0.1:<port>/healthz   # 200 == alive

# Kill a phantom daemon you accidentally spawned:
PM2_HOME=/Users/<user>/.hermes/profiles/<agent>/home/.pm2 pm2 kill
# Exactly one God daemon should remain:
ps -ef | grep "PM2.*God" | grep -v grep | wc -l   # -> 1
pm2 save
```

If killing the port's PID respawns it instantly, that's the real daemon supervising it — not a zombie. Don't fight it; pin PM2_HOME and restart properly.

## 2. "Numbers are stale" — separate the data pipe from the renderer

A dashboard showing old numbers is usually an UPSTREAM data-pull failure, not a server bug. For <agent-d>: the Monarch browser pull logged out, so nothing got written. The cron's `last_status: ok` is misleading for LLM-driven jobs — it means the agent turn finished, not that the DB was written. Verify the write target (DB rows + as_of dates) directly.

## 3. Write-completeness trap (the subtle one)

A refresh script can update headline totals while leaving detail tables and trend snapshots frozen. <agent-d>'s `daily_pull.py` updated `cash_position`/`net_worth`/cash tier but never wrote back individual `cash_accounts` rows or appended a `net_worth_snapshots` row — so the hero refreshed while detail rows and the sparkline stayed at the May baseline. When fixing a stale dashboard, verify EVERY surface the data feeds, not just the headline:
- headline/aggregate row(s)
- per-item detail tables (with their own `as_of`)
- time-series/snapshot tables that power trend charts

## 4. Make stale data visible (renderer side)

Don't let a dashboard present stale numbers as if live. Add a freshness banner that surfaces the OLDEST dated input, and per-value "Nd old" pills with green/amber/red thresholds (e.g. fresh ≤2d, aging ≤7d, stale >7d). A beautiful dashboard fed stale data is actively dangerous because it looks authoritative.
