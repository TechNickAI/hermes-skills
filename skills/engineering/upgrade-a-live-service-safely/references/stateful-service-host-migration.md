# Migrating a stateful service to a new host

Moving a live, stateful service (trading agent, gateway, anything with a local
database plus credentials plus scheduled jobs) from one box to another. Worked
end-to-end on the a trading agent the co-tenant host → trading.<internal-domain> cutover, 2026-08-12.

The governing rule: **a copy is not a migration until you have diffed what you
believe copied against what actually did.** Four separate things looked fine and
were wrong in that one session.

---

## 1. Fence the source before the final sync — and confirm by PID

A checklist is not a fence. "Disabled, stopped, revoked" does not prove that a
cron-launched child, a queued turn, or a restart policy cannot act later.

**`systemctl stop` on a busy agent gateway is ASYNCHRONOUS and can be
preempted.** Observed: `systemctl --user stop` returned

```
Job for hermes-gateway-<profile>.service canceled.
```

because a long-running LLM subprocess was mid-flight and `TimeoutStopSec=210`
had not elapsed. The unit then reported **`active / disabled`** — which reads
like success at a glance and is not. Trading state was still live.

Correct method:

```bash
U=hermes-gateway-<profile>.service
PID=$(systemctl --user show "$U" -p MainPID --value)   # capture FIRST

systemctl --user disable "$U"        # cannot return on boot
systemctl --user stop "$U" &         # allow the full drain window
for i in $(seq 1 60); do
    st=$(systemctl --user is-active "$U")
    [ "$st" = "inactive" ] || [ "$st" = "failed" ] && break
    sleep 5
done

# THE check that matters — unit state lies, the PID does not
kill -0 "$PID" 2>/dev/null && { kill -TERM "$PID"; sleep 20; }
kill -0 "$PID" 2>/dev/null && echo "*** SURVIVED ***" || echo "pid gone"

# and prove no stragglers of the class you care about
pgrep -af 'crawdad_|<guard_runner>' | grep -v grep
```

**Never confirm a stop by unit state.** Confirm by PID death plus an explicit
process sweep. A `failed` final state is fine here — it means the drain window
expired, not that anything is running.

### A fence is not permanent until you disarm what restores it

The fence above held for 20 minutes and then **undid itself**: a
`*-liveness-watchdog` cron on the source host, running every 15 minutes, exists
precisely to notice a stopped gateway and start it. It did its job. With the
service already live on the new host, that is a split-brain generator.

Before declaring a source host fenced, enumerate everything that could revive
the service and disable it explicitly:

```bash
# 1. the unit's own restart policy + boot symlink
systemctl --user show "$U" -p Restart -p UnitFileState
ls ~/.config/systemd/user/default.target.wants/ | grep -i <svc>

# 2. the process manager's SAVED boot list — pm2 resurrects from a dump,
#    so `pm2 stop` alone comes back on reboot
python3 -c "import json;print([a['name'] for a in json.load(open('$HOME/.pm2/dump.pm2'))])"
pm2 delete <svc-entries> && pm2 save

# 3. crontab entries that restart things
crontab -l | grep -iE 'restart|start|systemctl|pm2'

# 4. the agent framework's OWN scheduled jobs — search the whole job blob,
#    not just names
python3 - <<'PY'
import json
jobs = json.load(open('.../cron/jobs.json'))
for j in (jobs.get('jobs') or jobs):
    if j.get('enabled') is True and any(
            k in json.dumps(j).lower()
            for k in ('restart','systemctl','resurrect','pm2','<svcname>')):
        print(j.get('name'), j.get('schedule'))
PY

# 5. watchdog SCRIPTS on disk
grep -rlE 'systemctl --user (start|restart)' ~/.hermes/scripts ~/<app> 2>/dev/null
```

Record a `paused_reason` on each disabled job naming the migration, so the next
reader knows it was deliberate and why re-enabling is harmful.

Note that a well-written watchdog may document how to bypass the framework's own
safety guards (e.g. assembling the words "re"+"start" from shell variables to
dodge a command-text filter). Treat those as high-priority to disarm — they are
by construction the ones that will succeed.

### Why the fence must precede the target starting

Single-holder resources make co-running actively harmful, not just untidy. A
Telegram **bot token allows exactly one poller**: two gateways each receive a
random half of messages. Enumerate every single-holder resource (bot tokens,
exchange sessions, advisory locks, webhook subscriptions) before overlapping any
window.

---

## 2. Verify the data by SEMANTICS, not row counts

Row counts prove almost nothing. A migration can move every row and still be
wrong. Checks that actually discriminate:

```python
# PK SETS, not counts — catches swapped/duplicated rows that keep the count
s = {r[0] for r in sqlite.execute("select pick_id from approvals")}
p = {r[0] for r in pg.execute('select "pick_id" from "approvals"')}
assert s == p, f"missing={len(s-p)} extra={len(p-s)}"

# money EXACT per-row AND in aggregate — float coercion hides in totals
assert all(float(s[k]) == float(p[k]) for k in s)
assert abs(sum(s.values()) - sum(p.values())) < 1e-9

# categorical histogram — catches silent row mangling
# {'BUY_PLACED': 51, 'CLOSED': 17, 'FILLED': 4, 'PROPOSED': 1} both sides

# exactly-once invariants survived the move
select "entry_order_id", count(*) from "approvals"
where "entry_order_id" <> '' group by 1 having count(*) > 1
```

**Sequences:** the classic SQLite→Postgres trap is a sequence left below
`MAX(id)`, so the first insert collides. Check rather than assume — with TEXT
primary keys there is no sequence at all:

```sql
select sequence_name from information_schema.sequences where sequence_schema='public';
```

**Timestamps:** keep the storage shape. Half-converting some TEXT ISO strings to
`timestamptz` while leaving INTEGER epochs alone silently changes meaning.
Migrate the shape, verify min/max bounds match, convert later as a deliberate
schema change.

### Write the schema translation as code, not by hand

For small tables (hundreds to low thousands of rows) that need type judgment,
generating DDL from `pragma table_info` beats both hand-transcription and
pgloader: nothing is lost in transcription, and the type map is reviewable.
Conservative mapping (`INTEGER→BIGINT`, `REAL→DOUBLE PRECISION`,
`TEXT→TEXT`, `BLOB→BYTEA`) plus a `--check` mode that prints the plan and DDL
without writing.

---

## 3. Postgres role isolation: PUBLIC CONNECT is granted by default

Creating a `shadow` database next to a live one does **not** isolate them. Every
new Postgres database grants `CONNECT` to `PUBLIC`, so any role reaches any
database. First isolation test caught the shadow role reading the live ledger —
exactly the phantom-writes contamination shadow mode exists to prevent.

```sql
REVOKE CONNECT ON DATABASE live   FROM PUBLIC;
REVOKE CONNECT ON DATABASE shadow FROM PUBLIC;
GRANT  CONNECT ON DATABASE live   TO live_app;
GRANT  CONNECT ON DATABASE shadow TO shadow_app;
```

**Test isolation in BOTH directions and require the denials to fail:**

```
live_app   -> live    PASS
shadow_app -> shadow  PASS
shadow_app -> live    PASS (denied)   <- the one that matters
live_app   -> shadow  PASS (denied)
```

Also: **an RDS master user is not a true superuser.** `CREATE DATABASE x OWNER
other_role` fails with `must be able to SET ROLE "other_role"`. Fix:
`GRANT other_role TO <master>;` first.

---

## 4. Diff what you believe copied

A profile/config directory copy can look complete and be missing the whole point
of the service.

Observed: source had **37 skill directories**, target had **14** — and the
missing ones were exactly the agent's domain knowledge (`kalshi-api`, `a trading agent`,
`trading`, `ops`). A fresh install **scaffolds its own bundled defaults**, so the
directory is populated and looks healthy while the irreplaceable part is absent.

```bash
# on each host
find <dir>/skills -name SKILL.md | sed 's|.*/skills/||' | sort > /tmp/h.txt

# REQUIRE this to be empty — nothing on source may be missing from target
comm -23 /tmp/source.txt /tmp/target.txt
# target having MORE is fine (bundled defaults)
```

Generalize: for every directory you migrate, produce a sorted inventory on both
sides and assert the source-only set is empty. Do not eyeball counts.

---

## 5. Scheduled jobs carry absolute paths from the old host

Migrated cron/job definitions can reference directories that exist only on the
source. Observed: the single enabled job had
`workdir=/home/ubuntu/a trading agent/current/polymarket-copytrade`, absent on the
target — it would have failed every 15 minutes, silently, forever.

**Before starting the scheduler on the new host, validate every enabled job's
`workdir` and `script` against the NEW filesystem.** Disable what does not
belong there and record a `paused_reason` so the next reader knows it was
deliberate.

---

## 6. `RequiresMountsFor=` is silently inert in a systemd USER unit

State on a separate volume needs a guard, and the obvious directive does not
work in user units. It is accepted, echoed back by `systemctl --user show`, and
even resolved to the real mount unit — but `Requires=` only ever contains
`basic.target` and `app.slice`, because a **user** manager cannot depend on a
**system** mount unit.

Proven by unmounting the volume and starting the service: it started, and would
have written live state to the root disk while reporting healthy.

```bash
#!/bin/bash
# require-state-volume.sh  — ExecStartPre
set -u
MP=/srv/<app>/shared
mountpoint -q "$MP"     || { echo "FATAL: $MP not mounted" >&2; exit 1; }
[ -f "$MP/config/env" ] || { echo "FATAL: wrong/empty volume" >&2; exit 1; }
touch "$MP/.probe" 2>/dev/null || { echo "FATAL: not writable" >&2; exit 1; }
rm -f "$MP/.probe"
```

Three conditions, because each defeats the previous: `mountpoint` passes on an
empty directory that happens to be a mount; a marker file proves it is the RIGHT
volume; a write probe catches a read-only remount, which `mountpoint -q` happily
accepts.

**A guard is not verified until you cause the condition and watch it refuse.**
Unmount → attempt start → confirm failure → restore → confirm success. After
testing a `Restart=always` unit this way, `systemctl --user stop` +
`reset-failed` or it retry-loops in `activating`.

---

## 7. Know which supervisor owns what

Do not assume one supervisor runs everything. On the source host the **gateway
was a systemd user unit** while **pm2 ran the dashboards**. A deploy script
written against the wrong one (`systemctl stop <wrong-name>`) **silently
no-ops** and then swaps the code tree under a live process.

```bash
systemctl --user list-unit-files --type=service
pm2 list
ls ~/.config/systemd/user/*.service
ps -eo pid,args | grep -E '[y]our-service'
```

A deploy must stop **everything that reads the prod tree** — including
dashboards whose pm2 `script path` points into it.

---

## 8. Reconcile against the external source of truth before arming

For anything touching an exchange/broker/payment API, the external system is
authoritative. Classify:

- **ORPHANS** — held externally, absent from the local ledger. **Must be ZERO.**
  An orphan is a real position nothing is protecting.
- **ghosts** — in the ledger, not held externally. Tolerable; usually settled.

Run the reconcile read-only from the NEW host, and separately from the old one:
identical balances/positions prove the same credentials and account scope, not
a split view.

---

## 9. Verify the backup includes the thing you just migrated

The migration is exactly when the new host first holds irreplaceable state. Run
the backup and then **prove the file is in the snapshot by name**:

```bash
restic -r <repo> ls latest | grep -E 'state.db$'
```

Empty output means it was not backed up, regardless of a green job.

---

## Post-cutover acceptance: reboot the box

Things that work today and never come back after a restart are the expensive
silent class. Do a real reboot (not a simulated one) and assert: volume mounted,
swap, security daemons, process manager resurrected, web layer serving,
database reachable — **and that the thing you deliberately left OFF is still
off.**

## Pitfalls

- **Judging a stop by unit state.** Capture MainPID first; confirm with
  `kill -0`.
- **Trusting a directory copy.** Sorted inventory + `comm -23` on both sides.
- **Row counts as migration proof.** PK sets, per-row money equality,
  categorical histograms, uniqueness invariants.
- **Assuming a new database is isolated.** Revoke `CONNECT` from `PUBLIC` and
  test both directions.
- **Assuming the RDS master can create objects owned by another role.**
  `GRANT <role> TO <master>` first.
- **`RequiresMountsFor=` in a user unit.** Use `ExecStartPre`, and test it by
  causing the failure.
- **One supervisor for everything.** Enumerate systemd (system AND user) plus
  pm2 before writing deploy stop/start logic.
- **Migrated job definitions with absolute source-host paths.** Validate every
  enabled job against the new filesystem before starting the scheduler.
- **Overlapping single-holder resources.** One bot token = one poller. Fence
  before starting the target.
- **A fence that undoes itself.** Liveness watchdogs, pm2's saved boot dump, and
  framework cron jobs all exist to restart stopped services. Disarm them
  explicitly, then re-fence and re-confirm by PID.
