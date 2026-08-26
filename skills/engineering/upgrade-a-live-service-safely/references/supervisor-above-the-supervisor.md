# The supervisor above the supervisor

Built and proven on 2026-08-14 for a trading agent's gateway on `trading.<internal-domain>`,
after the SAME terminal state was reached twice by different routes:

| date       | route                                                                                 | end state               |
| ---------- | ------------------------------------------------------------------------------------- | ----------------------- |
| 2026-08-12 | `daemon-reload` issued from inside the gateway's own cgroup SIGKILLed its supervisor  | `failed`, `NRestarts=0` |
| 2026-08-14 | a deploy stopped the gateway, then died at its own verify gate before the resume step | `failed`, `NRestarts=0` |

One hole, two incidents: **nothing asserts the service SHOULD be up,
independent of how it went down.** `Restart=always` is load-bearing for
crashes and is BY DESIGN blind to a client-requested stop.

## Choose a state assertion, not a deploy trap

The obvious fix is an `EXIT` trap in the deploy that restarts the service on
any exit path. **Prefer the state assertion instead.**

A trap only covers failure modes that run _through the deploy_. The
2026-08-12 outage did not go through the deploy at all, so a trap fixes one
of the two incidents. A periodic assertion fixes the class — it does not
care what stopped the service or whether that caller is still alive to clean
up after itself. (The trap is still worth adding as defence in depth; it is
just not the primary mechanism.)

Shape: a `oneshot` service + a timer firing every 60s, in the SAME systemd
user manager as the target unit but NOT in its cgroup.

## Pitfall 1 — the interlock must key on a live PROCESS, not a flag file

A deploy legitimately holds the service down while it drains in-flight work
and resets the tree. The watchdog must stand down during that, or it
re-opens exactly the unsafe window the deploy exists to provide.

**Do not gate on a flag/lock file.** The 2026-08-14 deploy died WITHOUT
cleanup — a stale flag would have suppressed the watchdog indefinitely,
rebuilding the very outage it was written to prevent. A process check cannot
go stale because the kernel reaps the evidence:

```bash
if pgrep -f 'deploy_wrapper\.bash|deploy-stage\.[^/]*/deploy\.bash|/srv/app/ops/deploy\.bash' >/dev/null 2>&1; then
    log "unit=$state but a deploy is live -- standing down"
    exit 0
fi
```

Match every argv shape the deploy can take, including the copy a
self-updating wrapper `exec`s out of a temp staging dir.

## Pitfall 2 🔴 — acting on `deactivating` CANCELS the pending stop

This is the defect the counterfactual caught, and it would have shipped.

The first version treated only `active|activating|reloading` as hands-off.
On a deliberate stop the watchdog fired while the unit was still
`deactivating`, and the queued start job **cancelled the in-progress stop**:

```
Job for hermes-gateway-<profile>.service canceled.
stop-exit=1
...
WARNING gateway.run: Gateway drain timed out after 180.0s with 2 active agent(s); interrupting remaining work.
⚡ Interrupted during API call.
```

The unit had `TimeoutStopSec=210` and drains in-flight agents on SIGTERM.
The "recovery" truncated a real drain and killed live work mid-API-call.
**Recovery must never be more destructive than the outage it repairs.**

Fix — act ONLY on a settled down-state:

```bash
case "$state" in
    active|activating|reloading|deactivating) exit 0 ;;
esac
```

Waiting costs nothing: once the stop settles to `inactive`/`failed`, the next
tick (≤60s) starts it. A deliberate stop is still corrected — just _after_
the drain is allowed to finish properly.

Also clear a latched failure first, or the activation is refused:

```bash
[ "$state" = "failed" ] && systemctl --user reset-failed "$UNIT" || true
```

## The counterfactual is mandatory, and it must be able to FAIL

> "If a deliberate stop does not trigger it, you have rebuilt
> `Restart=always` under a new name."

Run BOTH directions. A guard that cannot fail is decoration.

**CF1 — liveness.** `systemctl --user stop` the unit, then confirm the
watchdog brings it back on its own.

- Expect `stop-exit=0` (a clean completed stop, NOT `canceled`).
- Grep the journal for `canceled` afterwards — it MUST be empty, which is
  what proves the drain ran to completion untouched.
- Confirm a NEW `MainPID`, not just `ActiveState=active`.

**CF2 — safety.** Start a FAKE process matching the deploy interlock's
pgrep pattern, stop the unit, and watch ≥3 consecutive ticks confirm the
service stays DOWN and the log says "standing down". Then kill the fake and
confirm recovery on the next tick. Use a fake process — never run the real
deploy to test a watchdog, and keep money paths read-only.

Budget real time: with a 210s stop timeout, each counterfactual runs for
minutes. Run them detached (`nohup ... > /tmp/out.log 2>&1 &`) and poll the
log, because an SSH foreground call will time out mid-drain and tell you
nothing.

## Installing it without repeating the 2026-08-12 outage

`daemon-reload` is what caused the earlier incident. Before running it,
prove your shell is NOT in the target's cgroup:

```bash
cat /proc/self/cgroup     # want: .../session-NNNN.scope
systemctl --user show <unit> -p ControlGroup --value
```

A session scope is safe. If your shell is inside the service's cgroup, the
reload can kill your own supervisor. Verify the target survived the reload
by checking `MainPID` is unchanged afterwards.

Requires `loginctl show-user <u> -p Linger` = `yes` for user units to run
without a login session.

## Reporting shape

The watchdog should be SILENT on a healthy service (exit 0, no output) and
log one line per real action. the operator's alerting rule applies: a monitor that
reports "healthy" every minute is a defect, not observability.
