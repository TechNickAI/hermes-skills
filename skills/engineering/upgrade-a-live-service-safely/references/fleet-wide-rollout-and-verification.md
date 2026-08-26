# Rolling a code upgrade across a fleet of hosts

Covers the class: one pinned branch/tag, N hosts, each running one or more
long-lived gateway/daemon processes out of a git checkout. Written from the
one occasion v0.20.1 → v0.20.5 rollout across 8 hosts.

---

## 1. Survey EVERY host before you touch ANY host

Not "is it reachable" — capture the state a deploy would destroy:

```bash
cd "$CO"
git rev-parse --abbrev-ref HEAD; git rev-parse HEAD
git status --porcelain | wc -l # <-- the load-bearing one
git remote -v
```

**A dirty working tree on one box is the single highest-value finding of the
whole rollout.** On one occasion exactly one host of eight had 4 modified files —
66 lines that existed _nowhere else in the world_: not in the release tag, not
in the fleet branch, not in any commit. They were two real user-protecting
fixes. A `git reset --hard` would have silently reverted them, and one of them
was the fix stopping the agent from texting pairing codes to the owner's real
contacts.

**Never classify a dirty tree as "drift" or "debris" to be cleaned.** Read the
actual diff and decide deliberately. Uncommitted work on a production box is
usually someone solving a real problem under pressure.

## 2. The deploy script must REFUSE a dirty tree

Make this structural, not a thing you remember to check:

```bash
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$DIRTY" != "0" ]; then
  echo "FAIL: working tree has $DIRTY modified file(s). Refusing to reset." >&2
  git status --short >&2
  exit 1
fi
```

This is what makes a batch loop safe to run across all hosts at once: the one
host with owner edits fails closed while the rest proceed.

## 3. Rescuing owner edits into the branch

When the dirty files turn out to be genuine fixes:

1. **Back up twice** — pull the diff to your workstation AND write it to the
   host's own `~/fleet-local-work/`. Verify with `shasum -a 256` that both
   copies match.
2. **Prove it applies** to the new branch before committing to a plan:
   `git apply --check <patch>`.
3. **Sabotage-test the fix** so you know the accompanying tests actually bind
   to it, not just that they pass.
4. **Prove preservation semantically**, not by file hash. The files will differ
   (they also carry the upgrade's own changes). Compare the _added lines_:

```bash
grep '^+' theirs.diff | grep -v '^+++' | sed 's/[[:space:]]*$//' | shasum -a 256
grep '^+' mine.diff | grep -v '^+++' | sed 's/[[:space:]]*$//' | shasum -a 256
```

Identical hashes = their work survived byte-for-byte.

## 4. Verify BEHAVIOR, not string presence

`git rev-parse` proves the source moved. It does not prove the running process
loaded it, nor that the install is coherent. Assert three layers:

| Layer    | Check                                                       |
| -------- | ----------------------------------------------------------- |
| Source   | `git rev-parse HEAD` matches target                         |
| Install  | `importlib.metadata.version(pkg)` is the NEW version        |
| Behavior | actually invoke the changed code path and assert the output |

The third one is what catches a half-deploy. Running the changed security
scanner against real fixtures (`prose -> safe`, `inline-shell -> dangerous`)
proves the new logic is live in a way no string grep can.

### The half-deploy this actually caught: uv venvs have no pip

On one occasion the dependency-resync step failed on **6 of 7 hosts** with

```
/home/ubuntu/.hermes/hermes-agent/venv/bin/python: No module named pip
```

The venvs were created by **uv**, which does not install pip inside them.
Confirm from the venv's own marker rather than guessing:

```bash
cat "$CO/venv/pyvenv.cfg" # a `uv = 0.12.4` line means no pip
```

Reinstall with `uv pip`, naming the interpreter, and export `~/.local/bin`
first because it is not on PATH over non-interactive SSH:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv pip install --python "$CO/venv/bin/python" -q -e ".[messaging,cron,cli,voice]"
```

Two rules that go with it:

- **Always name the extras.** A bare `-e.` drops the messaging stack and the
  gateway comes back up deaf. Re-assert the key packages after the install
  rather than trusting the exit code.
- **Do not install pip into the venv to "fix" it.** That puts two package
  managers on one site-packages. Use `uv pip`.

The failure mode this creates is the reason layer 2 exists in the table above:
the checkout was already at the new commit, so a `git rev-parse` check reported
success, while `importlib.metadata.version` still said `0.20.1` on five hosts.
Code imports fine in that state. Only asserting source AND installed metadata
AND behavior catches it.

## 5. Prove a restart by PID CHANGE

`systemctl is-active` / `launchctl list` returning something is not proof. Capture
the PID before, restart, then poll until it differs:

```bash
B=$(systemctl --user show "$U" -p MainPID --value)
systemctl --user restart "$U"
for i in $(seq 1 30); do
  sleep 2
  A=$(systemctl --user show "$U" -p MainPID --value)
  [ "$(systemctl --user is-active $U)" = active ] && [ -n "$A" ] && [ "$A" != 0 ] && [ "$A" != "$B" ] && break
done
[ "$A" = "$B" ] && { echo "PID UNCHANGED - not proven"; exit 1; }
```

## 6. Two log/status readings that look like failures and are not

**`Failed with result 'exit-code'` immediately before `Started`.** That is the
OLD process exiting during the stop phase. Read the precise timeline before
raising an alarm:

```bash
journalctl --user -u "$U" --since "5 minutes ago" -o short-precise \
  | grep -E "Stopping|Stopped|Started|Main process"
```

If `Main process exited` precedes `Started`, and `NRestarts` is 0 and stable,
the unit is healthy.

**launchd's second column is the LAST exit code, not current state.** A live,
healthy agent shows `exit=1` (or `-9`) from its previous stop. Confirm liveness
against the process table instead:

```bash
ps -o pid=,etime=,rss=,comm= -p "$PID"
```

## 7. A restart that outlives your SSH timeout is UNKNOWN, not failed

A busy agent mid-turn can take minutes to drain. On one occasion the trading box
took ~2.5 min and blew a 180s timeout mid-restart. **Do not retry the restart** —
re-read state. It had already come up cleanly, and a blind retry against a
money-adjacent agent is the dangerous move. Reconnect, check
`is-active` + `MainPID` + `NRestarts` + the log timeline, and only then decide.

## 8. Back up state databases BEFORE restarting, using the online backup API

Never `cp`/`rsync`/`tar` a live SQLite database — you get a torn copy that reads
as corrupt. Use the backup API and gate the restart on `integrity_check`:

```python
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d: s.backup(d)
r = d.execute("PRAGMA integrity_check(100000)").fetchall()
ok = (len(r) == 1 and r[0][0] == "ok")
```

Enumerate every database the box owns — root profile _and_ each named profile —
not just the default one.

## 9. Ordering

Lowest-blast-radius canary first, user-facing and money-adjacent boxes in the
middle, your own host last. **Skip your own process entirely** if a lifecycle
guard blocks self-restart; hand the human one exact command plus a PID-change
verification, and say plainly that the session ends when they run it.

## 10. Report what you did NOT verify

A host deliberately skipped is a first-class line in the final table with its
old commit and its dirty-file count — not an omission the reader has to notice.
