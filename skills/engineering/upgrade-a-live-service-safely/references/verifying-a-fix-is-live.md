# Verifying a fix is actually live — evidence that survives scrutiny

Lessons from the one occasion the router cutover. The recurring failure is not a
bad deploy; it is **claiming a fix works on evidence that does not prove it**.

## The auth wall: when you cannot curl the endpoint

The fix was a guard in `getDatabaseStats()`, reachable via
`GET /api/settings/database`. That route requires a **dashboard session
cookie**, not an API key, so curl returned `401` — and the auth gate fires
**before** the patched function is ever reached. A 401 proves nothing about the
fix either way.

**Do not report "couldn't verify" and stop. Verify against the compiled
bundle:**

```bash
# Is the guard actually in the code the service is running?
grep -rlsF "no such (module|table): dbstat" \
  ~/src/App/current/.build/next/standalone
```

Then print surrounding context to confirm the logic survived minification, and
**diff against the rollback release** — the contrast is the proof:

```
NEW build: try{...FROM dbstat...}catch(a){if(/no such (module|table): dbstat/i
.test(a.message))return!1;throw a}
OLD build: unguarded "FROM dbstat WHERE name", guard string ABSENT
```

That is a verifiable claim. "The endpoint returned 401" is not.

## Absence of errors is not evidence

`journalctl | grep -c dbstat` returned **0 before and 0 after** the cutover.
That looks like proof and is worthless — the code path was never exercised in
either window. **A counter that reads zero on both sides of a change tells you
nothing.** Say so explicitly rather than presenting it as a pass.

## Exercise the real thing, and read the exit code before believing a failure

- The smoke test piped `curl` into `head -c 300`. `head` closes the pipe at 300
  bytes → SIGPIPE kills curl → `grep -q` fails on a truncated stream → reported
  "streaming FAILED". Streaming was perfect (8 SSE events, 1602 bytes) when
  captured to a **file**. Never use `head`, `read -n`, or an early `break` in a
  while-read loop on an SSE/long-poll/tail stream: they all kill the producer
  and manufacture a failure.
- The staging script exited **28**. That is curl's _timeout_ code, from a final
  `-m 10` probe that timed out while a test instance competed for a 2-vCPU box —
  not a release failure. Map a nonzero exit to its actual meaning before
  reporting a defect.
- Health probes report `http=000` under CPU contention. Re-probe after the
  competing process exits; a first-call latency of 8.3s followed by 0.003s is
  contention, not breakage.

## Distinguishing a real defect from a load artifact

`cache_size` read `-16000` while the persisted setting was `65536`. That is
consistent with the known "startup ignores persisted value" bug — but the read
came from a **fresh readonly connection**, which gets the default, not the
server's own pragma. Flag it as _consistent with_ the defect and name the
limitation. Do not upgrade a suggestive reading into a confirmed one.

Same discipline for memory: RSS 70 MB after restart vs 2.6 GB before is a fresh
process, not proof of a leak fix. Say "unproven under load".

## Pre-flight: disk, and the guard that prevents self-harm

Do not restart a service at 94% disk. Prune superseded releases first, but
**never delete the running one** — resolve the symlink and compare:

```bash
CUR=$(readlink -f ~/src/App/current)
[ "$(readlink -f "$OLD")" = "$CUR" ] && { echo "ABORT: that IS live"; exit 1; }
```

Pruning one stale release took the host from 3.1G → 54G free.

## Post-cutover checklist that actually proves the thing works

```
service systemd active + MainPID CHANGED (proves restart) + NRestarts=0
health loopback 200 AND public HTTPS 200
provenance readlink -f current -> the new release
inference real requests across EVERY distinct upstream backend, asserting
               the SERVED model name, not just HTTP 200
streaming >=2 SSE frames captured to a file (proves progress, not just open)
UI fetch the dashboard; a 307 -> /login -> 200 is normal auth, not
               an error. grep the followed page for "Application error"
bundle grep the fix's marker string in current/ (see above)
errors journalctl since restart — and say so if the count is
               uninformative
```

## Housekeeping that protects the evidence

- Reading a live WAL SQLite under write load intermittently raises "database
  disk image is malformed". It is a **torn read, not corruption** — a snapshot
  of `.sqlite` + `-wal` + `-shm` checked as a static file passed 4/4. Retry with
  in-process integrity verification (10 attempts); a copy verified on attempt 3
  is normal.
- Run `node`/`better-sqlite3` one-liners **from the repo dir** (`cd ~/src/App &&
node -e...`). From `$HOME` they fail with "Cannot find module", which looks
  exactly like a missing dependency.
- If a test writes to a live artifact (a synthetic failure row, a probe
  message), **remove it and say you did**. Leaving it poisons the series you
  just built to be trustworthy.
- When an adaptation script asserts before writing, a later `scp` can still
  upload the **unmodified template**. Verify the _uploaded_ file's contents on
  the remote host, not the local one.
