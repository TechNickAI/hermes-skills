# Repeatable CI-artifact cutover with atomic rollback

Executed one occasion on a live LLM router: **~15s downtime, 8/8 verification
gates green first try, zero rollbacks.** The same operation two days earlier had
caused a 30-minute fleet outage (on-box build blew past RAM, box swap-thrashed
until cloud auto-reboot).

## The pipeline

```
1. trigger CI workflow free arm64 runner, exact arch match, ~11 min, $0
2. download + sha256 verify refuse on mismatch
3. unpack to releases/<sha>/ verify native modules + any fork patches
4. start on TEST PORT w/ DB COPY run the full gate; ABORT here on any failure
5. snapshot the DB <-- the actual one-way door, see below
6. ln -sfn + mv -Tf atomic symlink swap
7. systemctl restart ~3s
8. verify prod, same gate ANY failure -> auto-rollback
9. prune to N releases
```

Layout: `~/app/{releases/<sha>/, current -> releases/<sha>, shared/.env}`, with
the unit's `WorkingDirectory` pointing through `current/`. The one-time
conversion from a fixed path to the symlink layout is the only risky step; do it
in the same script as the first cutover, with the unit file backed up.

## 🔴 DB migrations are the real one-way door — not the code

The naive claim "rollback is just flipping the symlink back" is **wrong** the
moment the new build boots against the live DB.

That release applied **11 pending migrations** on first boot (schema 122 → 133).
Two were destructive:

| migration                           | effect                                                      |
| ----------------------------------- | ----------------------------------------------------------- |
| `126_reasoning_routing_rules`       | 3 destructive statements                                    |
| `130_remove_unregistered_qwen_data` | `DELETE FROM provider_connections`, `DELETE FROM key_value` |

Flipping the symlink after that gives you **old code against a migrated
database** — often worse than the bug you were rolling back from.

**Therefore:**

1. **Enumerate pending migrations BEFORE deploying.** Compare max applied
   version in the live DB against migration files shipped in the artifact, and
   grep them for `DROP|DELETE|ALTER.* DROP|TRUNCATE`.
2. **Rehearse them on a throwaway.** The test-port instance must run against a
   _copy_ of the DB, so all migrations execute for real before prod sees them.
3. **Snapshot the DB immediately before cutover** — never a plain `cp` of a live
   WAL database.
   🔴 **Prefer python, and RETRY WITH VERIFICATION.** Two corrections to earlier
   guidance here, both measured on the router One case:
   - The `sqlite3` CLI **is** present on that host (3.45.1), so a
     `command -v sqlite3` guard takes the CLI branch — and the CLI's `.backup`
     failed 1 run in 10 against the busy WAL DB. Probe order matters.
   - `.backup` can _succeed_ and still hand you a torn snapshot, so verify the
     copy with `integrity_check` in the same attempt and retry on failure.

   ```bash
   if python3 -c "import sqlite3" 2>/dev/null; then
     for attempt in $(seq 1 10); do
       if python3 - "$LIVE_DB" "$DEST" <<'PY'
   import sqlite3, sys
   src = sqlite3.connect(sys.argv[1], timeout=60) # NOT ?mode=ro
   src.execute("PRAGMA query_only=ON")
   dst = sqlite3.connect(sys.argv[2])
   src.backup(dst); dst.close(); src.close()
   chk = sqlite3.connect(sys.argv[2])
   ic = chk.execute("PRAGMA integrity_check").fetchone()[0]
   chk.close()
   raise SystemExit(0 if ic == "ok" else 1)
   PY
       then break; fi
       sleep 2
     done
   else
     echo "FATAL: no safe SQLite backup path"; exit 1
   fi
   ```

   Live result: `attempt 1 torn → attempt 2 torn → attempt 3 verified`. Without
   the loop the deploy fails on a perfectly healthy database. Details:
   `references/sqlite-live-wal-false-corruption.md`.

   General rule: **a capability probe whose fallback is less safe must fail
   loudly, not degrade silently.** Prefer a third branch that aborts over an
   `else` that quietly does the risky thing.

**When there are NO pending migrations, say so explicitly** — it changes the
risk posture. Compare the artifact's highest migration against the live DB's
`MAX(version)`; if equal, rollback really is a clean symlink flip, and that is
worth stating in the go/no-go rather than leaving implied. 4. **Rollback must restore code AND data together.** One command, both. 5. Verify survivability after: row counts on tables the destructive migrations
touched.

## The verification gate: 8 checks, identical for test and prod

Reuse the _same_ function for the test port and the live port. Different checks
for the two is how a bad release passes staging.

```
health endpoint reports expected version
/v1/models -> 200 with auth
dashboard HTML renders (title present, no "Application error"/"__NEXT_ERROR")
a static asset from that HTML -> 200
real inference on 3 representative routes
streaming (>= 2 SSE frames)
```

**Include the UI, not just the API.** Prompted by the user asking "what about
the dashboard?" — an API-only smoke test passes happily while a broken
server-rendered UI or a bad static-asset path ships. Extract a real chunk URL
from the rendered HTML and fetch it; don't hardcode one (a hash-named file
unchanged between builds exists in _both_, so it proves nothing).

## Proving the artifact is actually the new build

Weak provenance checks are worse than none. Things that genuinely differ:

- a `BUILD_SHA` file (the emergency-restored build had **none** — untraceable)
- compiled route/page count (135 vs 132 — three new routes)
- `build-manifest` hash
- chunk filenames unique to the release

Also verify: native modules are the right arch (`file` → `ELF 64-bit ARM
aarch64`), and any fork patch is present in the bundle.

## 🔴 Before believing a smoke FAILURE, rule out the harness

A failing smoke check is not automatically a failing release. Two harness bugs
produced false results in one session — one would have blocked a good artifact,
the other would have shipped a bad one:

**1. `| head -c N` kills the producer (SIGPIPE) and fakes a streaming failure.**
The SSE check piped `curl` into `head -c 300`; `head` closed the pipe, `curl`
died, and `grep -q "event:"` reported FAILED. The server log showed
`disconnect: request_signal_aborted` — the server watching its _client_ hang up.

```
streaming captured to a FILE: 8 SSE events, 1602 bytes <- release is fine
same request | head -c 300: FAILED <- harness artifact
```

Capture to a file and count. Never pipe a stream into a truncating reader —
`head`, `read -n`, and an early `break` in a `while read` loop all do this.

```bash
curl -sN... > "$OUT" 2>&1
EV=$(grep -c '^event:' "$OUT" || true)
[ "${EV:-0}" -ge 2 ] || FAIL=1 # >=2 proves progress, not just connection
```

**2. A result variable computed and never read.** `SMOKE_FAIL` was assigned in
four places and never tested, so a release failing every inference check would
still exit 0 and read as "staged successfully." `shellcheck -S warning` flags
this as SC2034 — that single warning was the difference between a real gate and
theatre. Run it on every deploy/verify script.

**Corollary — auth-gated endpoints prove nothing about your fix.** A `401`/`403`
means the auth layer fired _before_ the code under test ever ran. When
`GET /api/settings/database` returned 401, the `dbstat` guard being verified was
never reached. Prove such changes against the built artifact instead:

```bash
grep -rlsF "no such (module|table): dbstat" "$REL/.build/next/standalone"
```

Assert the string is **present in the new bundle and absent from the rollback
target**. Presence alone is a coincidence; the pair is proof.

**Also distinguish a harness timeout from a service failure.** A final probe
using `curl -m 10` returned `http=000` and exit 28 (curl's timeout code) while
the service was healthy — the test instance was simply competing for a 2-vCPU
box. Re-probe directly before reporting an outage.

## Reading CI status before you let it gate a deploy

A red check is not automatically your red check, and "fail" is not one state.
Before treating any CI result as evidence about your change:

1. **Separate cancelled/timed-out from genuinely failed.** A job killed by
   `##[error]The runner has received a shutdown signal` / `The operation was
canceled` produced **no signal at all** — it is not weak evidence of a
   problem, it is zero evidence. Reporting it as a failure manufactures a
   concern out of nothing. Read the job log tail, don't trust the one-word
   conclusion.
2. **Reproduce the failure on the untouched base before blaming your diff.**
   Check out the exact upstream base commit your branch forked from, run the
   same test file / gate, and compare. Identical pass/fail counts on base and
   branch is a _proof_ the failure is inherited, not caused. On this session the
   base and branch both showed `40 tests, 38 pass, 2 fail` — the breakage came
   from maintainer commits pushed to the base hours earlier.
3. **Check whether the failing files are files you touched.** `git diff
--name-only base...HEAD` against the failing paths settles it in one command.
4. **Watch for gates that fail on inherited drift.** File-size/lint-baseline
   gates ("X > frozen N, cannot grow") trip on whatever the base already
   exceeded, regardless of your patch.

State the conclusion explicitly when reporting: _"N checks fail identically on
the unmodified base; our tests are green"_ is a very different sentence from
"CI is red", and only the first one is actionable.

- **The remote login shell may not be bash.** `ssh host '<bash syntax>'` fails
  with e.g. `zsh: command not found: mapfile`. Use
  `ssh host 'bash -s' <<'EOF'... EOF` for anything using bash builtins.
- **macOS bash is 3.2** — no `mapfile`/`readarray`. Test bash-5 constructs on
  the host that will actually run them, not on the Mac authoring them.
- **`A && B || C` is not if-then-else.** Shellcheck SC2015. In a rollback path
  this is a real bug: `C` can run even when `A` succeeded. Use explicit
  `if/then/else` for anything on the failure path.
- **Guard the prune step against deleting the running release.** Simulate
  `current` pointing at an _old_ release and confirm the prune SKIPs it.
- Releases can be multi-GB. Check free disk and keep `N=2..3`.
- Run `shellcheck -S style` and fix the real findings; some remain intentional
  (single-quoted remote commands are _meant_ to expand server-side, SC2016/2029).
- **Suppress the downtime watchdog for the maintenance window** with a
  self-expiring flag, and clear it via `trap... EXIT`.
