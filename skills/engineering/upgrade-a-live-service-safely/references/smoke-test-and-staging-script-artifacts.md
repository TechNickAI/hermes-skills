# Smoke tests and staging scripts that fail themselves

Three ways a staging run reports a broken release when the release is fine. All
three cost real time on the (one occasion). The SQLite torn-read
class is its own document — see `sqlite-live-wal-false-corruption.md`.

The unifying rule: **before believing a staging failure, check whether the test
caused it.**

## 1. `| head` makes a working SSE stream look broken

The smoke test piped curl into `head -c 300` and reported:

```
streaming FAILED
```

The stream was fine. `head` closes the pipe after 300 bytes, curl dies of
SIGPIPE, and `grep -q` sees a truncated stream. The server-side tell is
`disconnect: request_signal_aborted` — the server observing the _client_ hang
up, i.e. the test killed its own producer.

Proof, same build, same request, one minute apart:

```
captured to a FILE: 1602 bytes, 8 SSE events
                            message_start, content_block_start, ping, content_block_delta
piped through head -c 300: FAILED <-- reproduces the smoke result
```

**Never terminate a stream you are measuring.** `head`, `read -n`, and an early
`break` in a `while read` loop all kill the producer. Redirect to a file, let
the request complete, then count frames. Require `>= 2` frames so "opened" is
distinguished from "progressed".

## 2. `EXIT=28` is curl, not the release

A staging run ended `EXIT=28` with `live:20128 health http=000`, which reads as
"the live service is down". It was not — 28 is curl's timeout code, and the
final liveness probe used `-m 10` while a second full instance was competing for
a 2-vCPU box. Direct checks immediately after:

```
loopback:20128 http=200 8.271s <- the slow one
loopback:20128 http=200 0.086s
https://<router-host> http=200 0.035s
```

The 8.3s first response is the real signal: **staging on a small box degrades
live latency**, because the test instance is a full second copy of the app.
Give the final probe a generous `-m`, and read `http=000` as "probe timed out",
not "service down". Confirm against the public URL and `MainPID` before
alarming.

## 3. A result variable that is computed and never read

`SMOKE_FAIL` was assigned in four places and never tested. Every inference check
could fail and the script still exited 0, printing `=== staged at... ===` —
a staging gate that could not fail. Found by `shellcheck -S style` (SC2034,
"appears unused"), which is worth running on any deploy script; it also caught
real SC2015 `A && B || C` bugs on rollback paths in the same file.

After adding the gate it immediately earned its place by catching the (spurious)
streaming failure above. **A gate that has never failed is not proven — verify
it can fail.**

## Adapting a template script: verify the OUTPUT, not the edit

A `python3 - <<PY` block that patches a template aborted on an `assert` (an
anchor had already been rewritten by an earlier patch), so it never wrote the
file — but the surrounding `&&`-free shell continued and `scp`'d the
**unadapted template** to the router. The run then failed against
`REPO="OWNER/REPO"`.

Two habits that would have caught it:

```bash
# 1. verify the UPLOADED file, not the local one
ssh host 'grep -E "^(REPO|MARKER)=" /tmp/script.sh; \
          echo "asserts: $(grep -c "PRESENT" /tmp/script.sh)"; \
          bash -n /tmp/script.sh'

# 2. gate the upload on the adaptation actually succeeding
python3 patch.py && scp script.sh host:/tmp/ || echo "ADAPT FAILED — not uploading"
```

Also: extracting a script through a line-numbered file reader and stripping the
prefixes with a regex mangled quoting and produced a file that failed `bash -n`.
**Copy template scripts verbatim (`cp`), then patch** — never round-trip them
through a reader that reformats.

## Order of operations when staging reports a failure

1. **Is the failing step the test or the artifact?** Re-run the same assertion
   by hand, outside the pipeline, capturing to a file.
2. **Reproduce the exact pipeline** to confirm the harness is the cause — the
   file-capture version passing while the piped version fails is proof.
3. **Check the live service directly** before reporting an outage: loopback,
   public URL, `MainPID` unchanged, `journalctl` error count for the window.
4. Only then treat it as a defect in the build.

## Verification checklist before cutover

- `MainPID` unchanged from the pre-flight value (live never restarted)
- live health 200 on **both** loopback and the public URL
- `journalctl --user -u <svc>` shows zero errors during the staging window
- smoke exercised **real inference across several distinct upstream backends**
  plus streaming — four 200s from four different providers is the bar, not one
- migration parity: highest migration in the artifact == highest applied in the
  live DB. Equal means a symlink flip is a genuine rollback. Unequal means the
  DB is the one-way door — see `database-migrations-and-rollback.md`
- **free disk after unpack.** Releases are ~5.3 GB each; three of them took the
  router to **94% (3.1 GB free)**. Prune superseded releases _before_ restarting
  — a service that boots into a full disk is a bad failure mode, and the DB
  snapshot taken at cutover needs room too
