# The agent that corrupts its own database by shelling out to its own CLI

> **STATUS: SHIPPED one occasion.** The hardened helper is
> `skills/core/multi-review/scripts/reviewer_home.sh` in the public
> `hermes-skills` repo (PR #24, merged `6e0a485`), and the bundled
> the multi-review skill's parallel reviewer runner uses it. Installed and functionally
> verified on `a trading agent`, `dos`, and `the operations agent` — the only fleet members that have
> `multi-review` at all. Anyone standing up a new panel, or writing an
> equivalent fan-out by hand, still needs this file.
>
> **Rolling it onto a fleet copy: anchored INSERT, never overwrite.** Fleet
> copies carry the operator-authored `references/`, per-host tuning, and `.bak-*`
> siblings; a trading agent's was version 1.1.0 against upstream 1.4.1, so a copy would
> have destroyed real local work. The rollout that worked installed the new
> `scripts/` file (cannot conflict), anchored-patched the runner, and inserted
> the isolation section ahead of an existing heading — each step backed up,
> `bash -n`-checked, and rolled back on failure, with a `--check` dry-run mode
> first. This also sidesteps hub-install provenance: adding files and inserting
> at an anchor needs no curator write permission on the target.

**Measured on one run, `trading.<internal-domain>` / profile `a trading agent`.** A gateway had
corrupted repeatedly over several days (`delivery_obligations`, then four FTS
shadow tables, then structural B-tree damage in `messages`). Volume was the
leading hypothesis. It was wrong. The cause was a **second OS process writing
the same WAL database**, and that process was a **child of the gateway itself**.

## The one command that finds it

Run this BEFORE any volume, disk, or pragma analysis:

```bash
lsof -F pcfan /path/to/state.db
```

`a` is the fd access mode. `r` = read, **`u` = read/WRITE**. Any writer whose
pid is not the service's `MainPID` is the answer.

```
pid=2788769 cmd=hermes fd=33 mode=u GATEWAY
pid=2795631 cmd=hermes fd=6 mode=u *** NON-GATEWAY WRITER ***
```

Then read the parent chain — this is what names the mechanism:

```
2788769 hermes gateway run --profile a trading agent <- the gateway
  └─ 2795602 bash -lic... for M in gemini grok... <- agent's terminal tool
       └─ 2795631 hermes -z "Review PRODUCTION CODE..."
```

The gateway spawned a shell, which spawned a headless one-shot, which opened the
gateway's own `state.db` read-write.

## Why a headless one-shot is a writer (source, not inference)

A headless one-shot is not a lightweight API call. It boots a full agent and
attaches to the calling profile's live session store:

```python
# cli.py:4642
self._session_db = SessionDB()

# cli.py:8566
self._session_db.create_session(
    session_id=self.session_id,
    source=os.environ.get("HERMES_SESSION_SOURCE", "cli"),...)

# hermes_state.py:2798
self.db_path = db_path or _default_db_path() # -> the profile's state.db
```

Corroborating evidence in the data itself: **15,090 messages with
`source='cli'`** sitting in the gateway's own store — reviewer transcripts
nobody asked for.

Hermes' in-process concurrency is sound (one lock-protected writer plus a
bounded read-only pool, `check_same_thread=False` guarded by a real lock). That
lock lives **inside one process**. A second OS process has independent lock
state and its own view of the WAL index. **No pragma prevents this** —
`synchronous=FULL`, `busy_timeout`, and a non-vulnerable SQLite build were all
already in place here.

## Ruling out the usual suspects, by measurement

Do this so the second-writer finding is a conclusion and not a hunch:

| suspect              | how it was ruled out                                            |
| -------------------- | --------------------------------------------------------------- |
| SQLite WAL-reset bug | `is_sqlite_wal_reset_vulnerable()` → `False` on 3.53.1          |
| durability pragmas   | `synchronous=2` (FULL), `journal_mode=wal`, `busy_timeout=5000` |
| hardware / disk      | no `dmesg` I/O errors, no OOM, fs clean, `rotational=0`         |
| write volume         | see control population below                                    |

**Volume needs a control population before it can be blamed.** The corrupt
agent wrote 103,710 msgs/24h — 5.7x the next busiest. That sounds decisive until
you notice a peer firing _more_ scheduled jobs (1,800/day vs 3,086) stayed
perfectly healthy. Volume explains _why this box surfaced it first_; it is not
the mechanism. Only one agent was spawning a headless one-shot against itself.

## The fix — and the naive form of it is BROKEN

The instinct is to give the one-shot its own throwaway store:

```bash
HERMES_HOME=$(mktemp -d) hermes -z "..." --provider X -m Y -t '' # ← DOES NOT WORK
```

🔴 **Tested one occasion and it fails silently.** `HERMES_HOME` is not a
`state.db` pointer — it is the ROOT for `config.yaml`, `.env`, skills,
memories and cortex. An empty temp dir has none of them:

```
real profile config.yaml=True.env=True skills=True
empty temp config.yaml=False.env=False skills=False
```

Measured behaviour of a real one-shot under each home (`-z 'Reply with exactly
the word: PONG' -t ''`):

| case                                      | stdout                                    | exit  |
| ----------------------------------------- | ----------------------------------------- | ----- |
| A real home                               | `PONG`                                    | 0     |
| B **empty temp**                          | `HTTP 401: Missing Authentication header` | **0** |
| C temp seeded with `config.yaml` + `.env` | `PONG`                                    | 0     |

**Case B exits 0.** A caller that checks the exit code sees success while the
reviewer never ran. That is worse than a crash here: `multi-review` counts a
seat by whether the process returned output, so a five-model panel silently
degrades to zero real reviewers and still reports a completed review.

The working form seeds the credentials:

```bash
H=$(mktemp -d); chmod 700 "$H"
cp ~/.hermes/profiles/<p>/config.yaml ~/.hermes/profiles/<p>/.env "$H"/
HERMES_HOME="$H" hermes -z "..." --provider X -m Y -t ''
rm -rf "$H"
```

Two costs to state out loud before adopting it, rather than letting them be
discovered:

- **It copies credentials to a temp directory.** Needs `chmod 700` and reliable
  cleanup on every exit path, or corruption has been traded for a
  secrets-hygiene problem.
- **The reviewer loses skills and memory.** For a review panel that is arguably
  correct (`--ignore-rules` already strips the calling persona deliberately),
  but it is a behaviour change, not a free win.

## ✅ THE ACTUAL FIX: one EPHEMERAL scratch home PER REVIEWER

🔴 **A single shared reviewer profile is NOT sufficient — measured.** A
dedicated `-p reviewer` profile does move writes off the gateway, and a
single reviewer tests clean:

```
CONTROL: 15s, no reviewer caller state.db mtime changed on its own: False
exit=0 stdout: PONG <- real model call, credentials work
reviewer process EVER held caller's state.db: False
caller state.db size: 1889136640 -> 1889136640 (unchanged)
```

But a review panel fans out N reviewers **at once**, and two panels can
overlap. Tested with 6 concurrent reviewers against one shared profile:

```
PEAK simultaneous processes holding the db: 6
holder samples: [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 4, 1]
*** CONCURRENT WRITERS CONFIRMED -- shared profile is NOT enough ***
```

That is the original bug, relocated. Integrity happened to survive that run —
which proves nothing, because the production corruption took **days** to
develop. **One passing run is not evidence of safety here.**

The correct unit is **one throwaway `HERMES_HOME` per reviewer**, seeded with
credentials and deleted afterwards. Measured peak holders per database: **1**.

```bash
H=$(mktemp -d); chmod 700 "$H"
for f in config.yaml.env auth.json; do
  [ -f "$SRC/$f" ] && { cp "$SRC/$f" "$H/$f"; chmod 600 "$H/$f"; }
done
HERMES_HOME="$H" hermes -z "$PROMPT" -t '' --provider X -m Y
rm -rf "$H"
```

`auth.json` is **required**, not optional: it carries OAuth tokens for
providers that do not use a plain API key. Omitting it made a real `grok` seat
fail with _"No xAI OAuth credentials stored"_ while API-key seats passed — a
partial-credential failure that reads like a model outage.

Comparison of every candidate, all tested on the same box:

| approach                             | works | per-model prompts | safe when concurrent | no leftover state |
| ------------------------------------ | ----- | ----------------- | -------------------- | ----------------- |
| a headless one-shot as-is            | ✓     | ✓                 | ✗                    | ✓                 |
| bare `HERMES_HOME=$(mktemp -d)`      | ✗ 401 | ✓                 | ✓                    | ✓                 |
| MoA preset                           | ✓     | ✗                 | ✓                    | ✓                 |
| shared `-p reviewer` profile         | ✓     | ✓                 | **✗ 6 holders**      | ✗ sweep needed    |
| **per-reviewer seeded scratch home** | **✓** | **✓**             | **✓ peak 1**         | **✓**             |

**Measured cost** (macOS): seeding a home ~1.2 ms / ~26 KB; `state.db` created
on demand ~232 KB; 10 concurrent reviewers finished in 12.1 s using 2.7 MB of
scratch, fully removed. Creating a home is far cheaper than the model call it
wraps — never batch reviewers into one home to "save" it.

A scratch home also beats a named profile on hygiene: nothing is registered
under `profiles/`, so there is no namespace to sweep after a crash and no name
to collide with. The scratch dies with the run.

⚠️ `HERMES_PROFILE=<name>` is **silently ignored** — measured, it resolved to
the root `~/.hermes/state.db`. Only the `-p` flag selects a profile. Nested
profile names (`-p multi-reviewer/<id>`) fail `rc=2` with empty output.

## Bash traps that silently defeat the cleanup

Three measured failures, each of which made cleanup _look_ correct while it was
not. Any implementation of the scratch-home pattern must handle all three.

**1. `P=$(pool_init)` self-destructs.** Command substitution runs the function
in a **subshell**, so an EXIT trap armed inside fires the moment the
substitution closes — deleting the scratch before use. This produces the
nastiest possible test result: the first crash test "passed" only because the
pool was _already gone_, so **never-survived looked identical to cleaned-up**.

An owner-pid guard does **not** rescue it: bash keeps `$$` as the parent's pid
inside a subshell, and `BASHPID` is **empty on bash 3.2** (macOS `/bin/bash`) —
verified, the guarded and unguarded variants behaved _identically_ under
mutation test, which is the tell. Fix: have init **set a global** rather than
echo a path, and make lazy auto-init a hard error.

**2. A trap cannot fire while bash blocks in a FOREGROUND child.** Measured:

```
foreground `sleep 60` -> SIGTERM -> trap NEVER fired, scratch leaked
`sleep 60 & wait $!` -> SIGTERM -> trap fired, scratch removed
```

Background the child and `wait "$pid"`.

**3. A signal handler that does not exit lets the script RESUME.** Bash returns
control to the next statement, so a Ctrl-C'd fan-out destroys the pool and then
cheerfully seeds a new one and keeps spending model calls. Kill live children,
`trap - INT TERM EXIT`, then re-raise with `kill -s "$sig" "$$"`.

Also: **chain the caller's EXIT trap, do not clobber it** (this file is
`source`d into the caller's shell), and **do not export** the pool variable —
an exported pool is inherited by child shells that then adopt it and delete it
on their own exit while the parent's reviewers are still running.

## Fail closed, or the helper causes the corruption it prevents

The highest-severity defect found when this helper was itself multi-reviewed:

> "`reviewer_home` never checks mktemp. Verified with `TMPDIR=/nonexistent`:
> `mktemp -d` returns rc=1 and empty … Then `HERMES_HOME="" hermes -z` — and
> `env_loader.py:489` is `Path(hermes_home or os.getenv(...))`. **Empty string
> is falsy. The reviewer opens `~/.hermes/state.db`.** The isolation helper
> degrades into precisely the B-tree corruption it exists to prevent,
> silently."

So: validate every scratch path and **refuse to run** without one. Same for
credentials — a home missing `config.yaml` yields HTTP 401 **with exit code 0**,
which a fan-out scores as a successful seat. Refuse rather than produce a ghost
reviewer. Never `rm -rf` a caller-supplied directory itself; only a
subdirectory this code created inside it.

⚠️ `HERMES_PROFILE=<name>` is **silently ignored** — measured, it resolved to
the root `~/.hermes/state.db`. Only the `-p` flag selects a profile.

## MoA is the wrong SHAPE for a review panel — do not propose it

MoA looks like the answer ("ask several models, synthesize") and is not. The
distinction that decides it:

- **MoA broadcasts ONE prompt to N reference models**, then aggregates.
- **A review panel sends N DIFFERENT prompts to N models** — _"Grok, be
  ruthlessly critical"_, _"Claude, review with empathy for the author's
  intent"_, _"gpt, security lens only"_.

Per-model _persona/lens_ assignment is the entire point of the fan-out, and MoA
has no mechanism for it. Offering MoA as the replacement reads as not having
understood the requirement. Headless one-shots stay correct; only their session
store was ever the bug.

## Upstream has REFUSED per-task model in `delegate_task` — stop proposing it

Do not plan around this arriving. Researched One case:

- **Issue #17685** — the `model` field inside a task object is _"completely
  ignored… silently accepted and discarded — no error, no warning."_ A reporter
  with an 11-subagent research pipeline: _"this makes our skill's entire
  model-assignment table decorative."_
- **At least five PRs** tried to add it: #17718, #23266, #25026, #34773, #36790.
- Maintainer `teknium1` closed #34773 with **"We do not want this"**.
- Official docs state the pin is global and name the supported alternative:
  _"hand the task to the kanban board, which does support a per-task model
  override"_ — `hermes kanban create... --model X --provider Y`, or
  `hermes kanban set-model <task> <model> --provider <p>` later.

Consequence for `multi-review`: its execution hierarchy ranks native subagents
#1 and headless one-shots #2 _"when subagents cannot select model families."_
That condition is **permanently true**, so rank 1 is dead and the skill drops
to `-z` every time. The hierarchy needs correcting: headless one-shots
**with a reviewer profile** are rank 1 for genuine multi-model panels; kanban
per-task override is the supported in-product alternative; `delegate_task`
remains right whenever multiple model _families_ are not required.

## Testing an env-var fix: resolve, then RUN

The generalisable lesson. An env var that reroutes one file usually reroutes a
whole tree, so a two-stage test is the minimum:

1. **Resolve** — ask the code's own resolver what each path becomes
   (`_default_db_path()` under each `HERMES_HOME`). Cheap, and proves the
   redirect works.
2. **Run** — execute the real command under each variant and read stdout, not
   just the exit code. Stage 1 said the fix was fine; stage 2 produced the 401.

Include a **control case** (the unmodified environment) so a failure that is
really a harness problem is visible. In this session all three cases first
failed with `ModuleNotFoundError: No module named 'dotenv'` — the bare `hermes`
launcher picks up whatever `python` is first on `PATH`. Invoking through
`~/.hermes/hermes-agent/venv/bin/python` fixed it. Without a control, that would
have read as "the isolation breaks Hermes."

And **scope the assertion to what was actually isolated**: this test checked
live-`state.db` mtime across all three cases at once, so case A's legitimate
write made the file look touched and proved nothing about B and C. Re-run
without the control before claiming the live file was untouched.

## When shelling out is nonetheless CORRECT

Do not "fix" this by banning the pattern. Check whether the in-process path can
actually do the job first:

**`delegate_task` cannot select a model per child.** Verified in
`tools/delegate_tool.py` — `creds` is resolved once from `delegation.provider` /
`delegation.model` and applied to every child in the batch:

```python
# delegate_tool.py:3622-3626, inside the per-task loop
model=creds["model"],
override_provider=creds["provider"],
```

The `tasks[]` schema exposes `goal`, `context`, `role`, `output_schema` — no
model field. So a **multi-model panel** (gemini + grok + claude + kimi) genuinely
cannot be built from subagents, and a headless one-shot per model is the right
call. Use `delegate_task` whenever multiple model _families_ are not required;
it is in-process and never opens a second connection.

## Rules

1. `lsof -F pcfan <db>` before any volume/disk/pragma theory. One command.
2. A non-service writer that is a **descendant of the service** is the single
   highest-yield finding; check the parent chain, not just the pid.
3. Any agent-initiated a headless one-shot (or equivalent CLI re-entry) against its own
   profile must isolate its session store — use **one seeded, ephemeral
   `HERMES_HOME` per reviewer** (`config.yaml` + `.env` + `auth.json`, `0600`,
   deleted after). Do NOT use a bare `HERMES_HOME=$(mktemp -d)`: it returns
   HTTP 401 and exits 0. Do NOT use a single shared reviewer profile: 6
   concurrent reviewers produced 6 simultaneous holders of one database.
4. Fix it in the **repo that owns the workflow** (PR), not by editing the host —
   deploy-managed hosts revert host edits by design.
5. This is latent in **any** agent running a shell-fanout review pattern while
   its gateway is live. The busiest writer just hits it first. Check peers before
   calling it a single-host problem.
6. **Read the calling skill before blaming the caller.** `multi-review` defines
   an explicit execution hierarchy in which native subagents rank #1 and headless
   one-shots rank #2 _"especially when subagents cannot select model families."_
   The agent followed it correctly. The bug was never the choice of `-z`; it was
   that `-z` attaches to the live session store as a pure side effect. Diagnose
   the side effect, do not "correct" a decision that was already right.
7. When the durable fix belongs upstream or in a skill every agent loads, say so
   instead of shipping a local workaround — a per-host patch leaves the same
   latent bug in every other agent running that pattern.
8. **Search the issue tracker before declaring a capability missing.** Reading
   one code path proved `delegate_task` ignores per-task model; it did NOT
   reveal that five PRs had been refused, that the maintainer said _"We do not
   want this"_, or that the docs name kanban as the supported alternative. Code
   tells you what is; the tracker and docs tell you what is _intended_ and what
   is _supported instead_. Do both before proposing an architecture.
9. **Do not answer a fan-out requirement with a broadcast feature.** When the
   user needs different instructions per model, check that the proposed
   mechanism can vary the _prompt_, not just the _model_. MoA cannot.
10. **Prefer the product's own isolation primitive over an invented one** — but
    verify it holds under the real concurrency. A named profile (`-p`) is the
    first-class unit and looked like the answer; it failed once N reviewers ran
    at once. The winning form was still a Hermes primitive (`HERMES_HOME`),
    just applied **per reviewer** instead of per panel.
11. **Test isolation at the concurrency the workload actually uses.** A single
    reviewer passes under every candidate mechanism, which is why a one-seat
    test is worthless here. Fan out N, poll `lsof -t <db>` while they run, and
    assert **peak holders == 1** per database. "Integrity was ok afterwards"
    is not a substitute — the production corruption took days to appear.
12. **Dogfood the safety helper with the panel it enables.** Multi-reviewing
    this helper's own code surfaced 9 defects, including a `mktemp`-failure
    path that silently reverts to the caller's live database — the exact
    corruption the helper exists to prevent. Reviewers ran the code and built
    stub binaries to observe behaviour; that is the level of evidence to expect
    from a real panel, and it is worth the model spend on safety-critical
    infrastructure.
13. **Run the control before blaming your own change for a failed seat.** A
    `grok` seat failed inside the scratch home and looked like a
    credential-isolation bug; the same call failed **identically from the real
    profile**, making it a pre-existing provider-config gap. Without the
    control that becomes a phantom fix to working code.
14. **Fixing the helper is not fixing the workflow — grep for every launch
    site.** A PR reviewer caught that the bundled
    the multi-review skill's parallel reviewer runner, the file the docs tell users to
    copy for larger panels, still launched a bare a headless one-shot. Shipping the
    hardened helper beside an unhardened template leaves the _documented_ path
    exposed and reads as fixed. After hardening a safety helper, grep the whole
    skill (templates, references, examples) for the raw call it replaces.
15. **A safety helper needs hostile-path tests, not just a happy-path test.**
    Every one of these failed _silently_ and none would surface in a normal
    run: unchecked `mktemp` yielding an empty `HERMES_HOME` (falsy → falls back
    to the caller's live db, i.e. the exact corruption); lazy auto-init inside
    `$(...)` self-destructing and handing back an unseeded home; a signal
    handler that returns instead of re-raising, letting the script _resume_ and
    seed a fresh pool; a sourced `trap... EXIT` clobbering the caller's own
    cleanup; an exported pool variable inherited by children that delete it
    mid-run. Test each with a mutation that removes the guard and assert the
    test fails without it.
16. **`$(...)` and `&` break shell state you think you own.** Two distinct
    traps, both measured. A variable assigned inside a backgrounded function
    (`reviewer_run... &`) mutates only the _subshell's_ copy — the parent's
    live-PID list read `[]` while two reviewers ran, so its signal handler
    killed nothing; use `jobs -p`, which the parent evaluates. And a trap
    **cannot fire while bash blocks in a foreground child**: SIGTERM during a
    foreground `sleep` left the scratch dir behind, while `sleep 60 & wait $!`
    cleaned up correctly.
17. **Do not reach for a pid guard to detect a subshell.** `$$` keeps the
    _parent's_ pid inside a subshell, and `BASHPID` is **empty on bash 3.2**
    (macOS `/bin/bash`) — a guard written with either compares equal in both
    places and changes nothing. The mutation test proved guarded and unguarded
    versions behaved identically. Restructure so no subshell is involved (have
    the function set a global rather than echo a path).
18. **A cleanup test can pass because the thing was never created.** The first
    crash test "passed" only because `P=$(pool_init)` had already self-destructed
    — never-survived is indistinguishable from cleaned-up. Assert the resource
    is **alive before** the kill, then gone after. Same shape as the mtime
    attribution error above.
19. **Signals reaching a shared process group can mask a broken handler.** After
    fixing the PID tracking, orphan reviewers did not reproduce — but only
    because SIGTERM hit the whole process group, not because the handler worked.
    That is incidental and would not hold for a `setsid`'d or TERM-ignoring
    child. Judge the finding on the mechanism, not on whether the symptom
    reproduced once.
20. **This fix removes one trigger, not the class.** Post-rollout, a trading agent still
    showed two writers on his live `state.db`: the gateway plus an interactive
    `hermes -p a trading agent --cli` session holding fd mode `u` for 1h25m. Any CLI
    re-entry against a live profile is the same bug. Say this out loud when
    reporting the fix, or the panel work reads as closing the whole problem.
