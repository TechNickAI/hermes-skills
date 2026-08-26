# Runtime vs on-disk version verification

**The rule: the version that matters is the one LOADED BY THE RUNNING PROCESS.**
Probing an interpreter, library, or package on disk tells you what the NEXT start
will use — not what is executing right now. On a long-lived service those differ
for days, and the gap is exactly where false "we're patched" reports come from.

Proven on the fleet one occasion/11 while remediating the SQLite WAL-reset
corruption bug (`references/sqlite-live-wal-false-corruption.md` covers the
corruption itself). The first survey declared four hosts "vulnerable" and one
"safe". Every one of those readings was wrong in some direction, and the
recommended remedy was a false remedy.

## The trap

Some dependencies are **statically compiled into the interpreter binary**, not
linked as a shared library. SQLite is one: `_sqlite3` reports
`__file__ == builtin` and `/proc/<pid>/maps` contains **no** `libsqlite3` entry.

Consequences that break the obvious mental model:

- The fix ships as a **new interpreter build** (here: a uv CPython build), not as
  an application release.
- The app version is byte-identical before and after — every host read
  `v0.20.0` throughout. **Version-of-the-app is not version-of-the-dependency.**
- The app's own updater does **not** fix it. Recommending it is a false remedy
  that closes the ticket while leaving the vulnerability live.
- A package manager can replace `cpython-3.11.14` with `cpython-3.11.15` under
  `~/.local/share/uv/python/` at any time. The venv symlink then resolves to a
  patched binary while every already-running process keeps executing the old
  inode.

Net: the host is **patched on disk and still vulnerable in memory**, and the
naive probe reports the opposite of the truth.

```bash
# WRONG — reads the NEW on-disk interpreter, reports a host as fixed when it isn't
<venv>/bin/python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

## The correct probe

**Linux** — `/proc/<pid>/exe` is executable directly, even after the underlying
file is replaced:

```bash
NP=$(systemctl --user show <unit> -p MainPID --value)
ls -l /proc/$NP/exe # a "(deleted)" suffix == running a stale binary
/proc/$NP/exe -c 'import sqlite3; print(sqlite3.sqlite_version)' # TRUE running version
```

`(deleted)` is the highest-signal indicator available: it means the on-disk
binary was swapped out from under a live process.

**macOS** — no `/proc`; recover the real binary from the open text segment:

```bash
for p in $(pgrep -f "<service pattern>"); do
  BIN=$(lsof -p $p 2>/dev/null | awk '/txt/ && /python3.11/ {print $NF; exit}')
  echo -n " PID $p uses $BIN -> "; "$BIN" -c 'import sqlite3; print(sqlite3.sqlite_version)'
done
```

Compare against the on-disk reading. The mismatch **is** the finding.

Date the swap to corroborate: if the interpreter directory's mtime is newer than
the service's start time (`ps -o lstart= -p <pid>`), every process older than
that timestamp is running unpatched code.

## Remediation follows from the mechanism

When the patched interpreter is **already on disk**, remediation is a plain
**service restart** — no download, no version bump, no config change. Do not
schedule an "upgrade" for something a bounce fixes; that inflates blast radius
and the change window for zero benefit. Getting the mechanism right shrank this
job from a four-host coordinated upgrade to four restarts.

Verify the restart actually remediated:

- [ ] MainPID **changed**
- [ ] `/proc/<newpid>/exe` no longer shows `(deleted)`
- [ ] per-PID probe reports the patched version
- [ ] symptom count is zero AFTER the restart timestamp (not "since the file began")

## Two measurement errors that nearly shipped alongside the fix

1. **String-comparing timestamps across dates.** `awk '$2 > "01:19:50"'` over a
   multi-day log matches every day's post-01:19 lines, not today's — it reported
   12 post-restart errors that were actually from the night before. Anchor the
   date: `awk '/^one occasion/ && /pattern/'`, or bucket with
   `grep pattern log | cut -c1-13 | sort | uniq -c` and read the histogram.
2. **Declaring a host "safe" without asking why.** One host passed only because
   its venv happened to point at a newer interpreter; its separate tool install
   still carried the vulnerable build. Correct posture, accidental cause — say so
   explicitly. An unexplained pass is not a verified pass.

## Generalization

Not SQLite-specific. Apply the same runtime-vs-on-disk discipline to any
statically-linked or interpreter-embedded dependency (OpenSSL, zlib, libffi,
expat) and to the application itself after `pip install -U` into a live venv.
**Ask "what is this PID actually executing?" before reporting any host's
remediation status.**

## The half-deploy: source moved, install metadata did not

An editable git-checkout install has a second version surface that drifts
independently of the source tree. `git checkout` moves the code immediately,
while `importlib.metadata.version(<pkg>)` keeps reporting the OLD version until
the editable install re-runs. The code _imports fine_ in that state, so a
`git rev-parse` check alone reports a successful deploy.

Observed fleet-wide one occasion (v0.20.1 → v0.20.5): every host showed the new
commit while the recorded dist version still read `0.20.1`, because the
reinstall step had failed.

**Assert all three, not one:**

1. source — `git rev-parse HEAD` matches the intended commit
2. installed metadata — `importlib.metadata.version(<pkg>)` matches the release
3. a real behavior probe — exercise a function that only exists or only behaves
   correctly in the new version

Point 3 is what makes the check non-fake. Prefer a probe with a two-way outcome:
feed a fixture the new code must ACCEPT and one it must REJECT, and assert both.
A version string equality can pass across hundreds of commits; a behavior probe
cannot.

### uv-created venvs have no pip

`python -m pip install -e.` fails with `No module named pip` on any venv uv
created — confirmed on 6 of 7 fleet hosts. Detect it by a `uv = <version>` line
in `venv/pyvenv.cfg`. Reinstall with uv, and **name the extras explicitly**:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv pip install --python "$CO/venv/bin/python" -e ".[messaging,cron,cli,voice]"
```

A bare `-e.` silently drops the messaging stack. After reinstalling, verify the
extras survived by importing or version-checking a package from each one — a
successful install command is not evidence the extras are present.

Do not "fix" this by adding pip to the venv.

### Skip the reinstall when dependency metadata did not change

Gate the reinstall on an actual diff so routine deploys stay fast and low-risk:

```bash
if ! git diff --quiet "$BEFORE" "$AFTER" -- pyproject.toml setup.py; then
  # reinstall
fi
```

Then run the import smoke test BEFORE restarting anything, so a broken tree is
caught while the old process is still serving traffic.
