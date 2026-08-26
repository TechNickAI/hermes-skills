# Systemd directives that are silently inert

A systemd unit file is a config surface, and it fails in the exact shape this
skill exists to catch: the directive is **accepted, parsed, echoed back by
`systemctl show`, and does nothing.** No error, no warning, no log line.

`systemd-analyze verify` will not catch these either. Only behavior will.

---

## Case: `RequiresMountsFor=` in a USER unit (verified one occasion)

### What happened

A trading agent's gateway had to refuse to start when its dedicated state
volume was missing. Without the guard the service starts, writes to the bare
mountpoint on the ROOT filesystem, and looks perfectly healthy — while all the
state it writes is on the wrong disk and outside the backup root. That is the
same class of silent failure that previously caused permanent data loss.

The unit (`~/.config/systemd/user/hermes-gateway-<profile>.service`) carried:

```ini
[Unit]
RequiresMountsFor=/srv/<app>/shared
```

Every static check passed:

```bash
$ systemctl --user show hermes-gateway-<profile>.service -p RequiresMountsFor
RequiresMountsFor=/srv/<app>/shared $HERMES_HOME
```

systemd even **resolved the path to a real mount unit** when asked:

```
-.mount
srv-<profile>-shared.mount
```

That is about as convincing as static evidence gets. It was still wrong.

### The behavioral test that found it

```bash
sudo umount /srv/<app>/shared
systemctl --user start hermes-gateway-<profile>.service
systemctl --user is-active hermes-gateway-<profile>.service
# -> active *** started with the volume gone ***
```

### Root cause

`Requires=` is where the dependency would have to materialize, and it never
did:

```bash
$ systemctl --user show <unit> -p Requires -p RequiresMountsFor
Requires=basic.target app.slice
RequiresMountsFor=/srv/<app>/shared $HERMES_HOME
```

**A systemd USER manager cannot take a dependency on a SYSTEM mount unit.**
Mount units live in the system manager; the user manager has no handle on them.
`RequiresMountsFor=` in a user unit parses, stores, displays — and is inert.

This is invisible to `systemctl show -p RequiresMountsFor`, which is precisely
the command you would reach for to "verify" it. You have to read `Requires=`,
the field where the resolved dependency would actually appear.

### The fix — an ExecStartPre guard

Replace the inert directive with a check that runs in the same privilege
domain as the service:

```ini
ExecStartPre=$HERMES_HOME/scripts/require-state-volume.sh
ExecStart=/…/python -m hermes_cli.main --profile a trading agent gateway run
```

```bash
#!/bin/bash
# Refuse to start unless the state volume is really mounted AND writable.
set -u
MP=/srv/<app>/shared

# 1. is it a mount at all?
mountpoint -q "$MP" || { echo "FATAL: $MP not mounted" >&2; exit 1; }

# 2. is it the RIGHT volume, not an empty dir that happens to be a mount?
[ -f "$MP/config/env" ] || { echo "FATAL: $MP mounted but empty/wrong" >&2; exit 1; }

# 3. is it WRITABLE? a remounted-read-only EBS still passes mountpoint -q
touch "$MP/.mount-guard-probe" 2>/dev/null || {
    echo "FATAL: $MP mounted but NOT WRITABLE" >&2; exit 1; }
rm -f "$MP/.mount-guard-probe"
exit 0
```

Three checks, because each catches a different real failure:
`mountpoint` alone misses an empty wrong volume, and both miss a volume that
remounted read-only after an EBS hiccup.

Retest after fixing — the same unmount now yields:

```
Job for hermes-gateway-<profile>.service failed because the control process exited
with error code.
   PASS: refused to start
```

### Cleanup gotcha

With `Restart=always`, a failing `ExecStartPre` leaves the unit in
`activating` and retrying forever. After the test:

```bash
systemctl --user stop <unit>
systemctl --user reset-failed <unit>
```

Otherwise a later check reports `activating` and you will misread it as
"still starting."

---

## The generalizable rule

**A systemd directive that `systemctl show` echoes back has not been verified.**
Verify a dependency by reading the field where it must MATERIALIZE
(`Requires=`, `After=`, `Wants=`), then prove it by removing the dependency and
confirming the unit refuses to run.

For anything protecting live-money or irreplaceable state, the behavioral test
is mandatory. "The config says so" is the failure mode, not the evidence.

### Sibling cases in the same family

- **`systemctl stop` is asynchronous and can be PREEMPTED.** On a busy agent
  gateway with a long-running child, `stop` returned
  `Job for … canceled` and the unit afterwards reported `active / disabled` —
  which reads like a successful fence and is not. Wait out the unit's real
  `TimeoutStopSec` (210s here), then **confirm the PID is gone with
  `kill -0 <pid>`**, not by trusting `is-active`. Capture `MainPID` BEFORE
  stopping; it is unreadable afterwards.
- **User units need a bus.** From a non-login context (CI over SSH),
  `systemctl --user` fails silently unless `XDG_RUNTIME_DIR=/run/user/$(id -u)`
  is exported. A deploy script that stops "the gateway" without this quietly
  no-ops and then swaps the code tree under a live process.
- **Know which supervisor actually owns the process.** On a host running both
  systemd user units and pm2, verify per-service which one supervises it. A
  deploy that calls `systemctl stop <name>` for a pm2-managed process (or the
  reverse) exits 0 having done nothing. Check `pm2 describe <name>` and
  `systemctl --user is-active <unit>` before writing lifecycle code.

## Checklist

- [ ] Directive read back from the field where it MATERIALIZES, not just the
      field where it was declared
- [ ] Guard proven by removing the dependency and watching the unit refuse
- [ ] Guard checks presence AND identity AND writability, not just presence
- [ ] Unit reset (`reset-failed`) after a deliberate failure test
- [ ] `XDG_RUNTIME_DIR` exported wherever `systemctl --user` runs non-interactively
- [ ] Supervisor ownership (systemd vs pm2) confirmed per service before
      writing start/stop logic
