# Runtime-linked SQLite refresh across a live fleet

Use this when SQLite is patched by replacing the interpreter underneath a running service. This is distinct from a Hermes package upgrade: Hermes and config may remain unchanged.

## Governing invariant

**Probe the binary loaded by the running gateway, not the interpreter currently reached through the venv path.**

A package manager can replace the interpreter target while a long-running process continues executing the old inode. A fresh invocation of `venv/bin/python3` then reports patched SQLite while the gateway remains vulnerable.

## Version scope

The SQLite WAL-reset corruption bug affects 3.44.0 through 3.44.5 and 3.50.0 through 3.50.6. Safe releases include 3.44.6+, 3.50.7+, and 3.51.3+.

In uv-managed CPython builds, SQLite can be compiled into the interpreter. Updating Hermes does not necessarily update SQLite. A new uv Python build can land on disk while active gateways retain the old interpreter until restart.

## Linux live-process probe

```bash
pid=$(systemctl --user show hermes-gateway.service -p MainPID --value)
ls -l /proc/$pid/exe
/proc/$pid/exe -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

A `(deleted)` suffix proves that the process holds a replaced binary. The `/proc/$pid/exe` invocation reports the version used by that live process. Do not substitute `venv/bin/python3`.

## macOS live-process probe

```bash
pid=$(launchctl list | awk '$3=="ai.hermes.gateway" {print $1}')
bin=$(lsof -p "$pid" | awk '/txt/ && /python3/ {print $NF; exit}')
"$bin" -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

Probe every gateway label on a co-tenant host. Root and named profiles are separate processes and can retain different binaries.

## Safe fleet sequence

1. Inventory every gateway process and record PID plus live SQLite version.
2. For owner-facing or keep-stable agents, create a live-safe SQLite online backup and verify it with `PRAGMA quick_check` before restart.
3. Confirm the patched interpreter exists on disk.
4. Restart each gateway through its supervisor.
5. Verify PID changed.
6. Probe SQLite through the new live PID.
7. Verify the original symptom is absent and the database is taking new writes.

## Restart verification traps

- `is-active` alone is insufficient. A unit can remain active while deactivating, and a restart can be queued while MainPID is unchanged.
- A systemd restart can take several minutes while Hermes drains an in-flight turn. Dispatch from a detached script, then poll MainPID, ActiveState, and `systemctl --user list-jobs`. Do not kill a productive turn because SSH timed out.
- On macOS, use the established launchd fallback, then prove PID change and inspect the new live binary.
- Match gateway labels exactly. Prefix matching can accidentally select helper units such as `ai.hermes.gateway-*-restart-once` and hang a rollout.
- A deep `PRAGMA quick_check` on a multi-gigabyte database can take minutes. Run it detached and poll a result file.

## Completion standard

Report a host fixed only when:

- every affected gateway has a new PID;
- every live process reports a safe SQLite version;
- required verified backups exist;
- the formerly damaged tables read successfully and integrity checks pass;
- the original error is absent after restart;
- fresh writes are visible after restart;
- WAL size is observed after restart rather than inferred from service health.
