# Changing a setting in a forked production service

Covers two joined problems: (1) a setting that _looks_ missing but actually
exists and is broken somewhere in its wiring, and (2) getting the resulting fix
onto a branch that matches what you actually run.

---

## Part 1 — Before adding a setting, trace the whole chain

**The trap:** the user asks to "make X configurable," you start writing a new
setting, and it turns out X was already configurable — just broken. You then
ship a duplicate mechanism next to a defective one.

**Rule: prove the setting is absent before adding it.** Trace all six links:

| Link                       | What to grep                                 | Failure mode found here             |
| -------------------------- | -------------------------------------------- | ----------------------------------- |
| 1. Type/interface          | `grep -n "<name>" src/types/*.ts`            | field declared but never read       |
| 2. Default value           | same file, the `DEFAULT_*` object            | default ≠ what UI writes            |
| 3. Persistence             | `key_value` table / settings store           | stale value from an old save        |
| 4. **Startup application** | `grep -rn "<pragma\|setting>" ` in boot path | **reads DEFAULT, not persisted**    |
| 5. Runtime re-application  | who calls `apply*Settings()`                 | only fires on save, not on boot     |
| 6. UI + API                | `grep -rn "<name>" src/app`                  | fallback literal writes wrong value |

### Worked case (the router `cacheSize`, one occasion)

Asked to "make the SQLite cache size configurable." It already was — with a UI
control, an API route, and an applier. Three separate defects instead:

**(a) Startup ignores the persisted value.**

```js
// src/lib/db/core.ts:1186
db.pragma(`cache_size = -${DEFAULT_DATABASE_SETTINGS.optimization.cacheSize}`);
```

Hardcoded to the compiled-in default. The stored value only lands later, when
`applyDatabaseOptimizationSettings()` runs on a settings _save_
(`databaseSettings.ts:309`). So a user-configured value **never survives a
restart**, and the dashboard displays a number the running DB does not have.

**(b) A UI fallback literal silently writes a wrong value.**

```jsx
cacheSize: parseInt(e.target.value) || 16384; // default is 65536
```

Clear the field or type junk → `parseInt` returns `NaN` → `|| 16384` persists
16 MB. That is exactly how production ended up at 16 MB against a 65536 default.
**Audit `||` fallbacks in numeric inputs — they must match the real default.**

**(c) The settings API was 500ing entirely.**

```
Error getting database settings: Error: no such table: dbstat
  src/lib/db/stats.ts:54:  SELECT SUM(pgsize) as size FROM dbstat WHERE name = ?
```

The whole page was dead, so the setting was unreachable via UI regardless.
Note `dbstat` tested **fine** from both the checkout's better-sqlite3 (12.11.1)
and the deployed standalone's (13.0.1), with `ENABLE_DBSTAT_VTAB: YES` — so it
is not a missing compile flag. Something about how the server opens its
connection loses the vtab. Mechanism still unproven; do not assert one.

### Answering "what happens if I unset it?" — test, don't reason

Copy the DB, delete the key, and observe. The merge logic usually clones
defaults and overlays stored keys, so absent ⇒ default:

```
WITH key:      key_value.cacheSize = 16384
after DELETE:  key_value.cacheSize = (ABSENT)   -> getDatabaseSettings() = 65536
```

But pair that with link 4: if boot hardcodes the default anyway, "unset" and
"set" can produce the _same_ boot behavior while differing after a save. Say
that explicitly rather than giving a one-word answer.

### Nested schemas: `.partial()` is top-level only

```ts
const patchSchema = databaseSettingsSchema.partial().strict();
```

Sending `{"optimization":{"cacheSize":65536}}` fails with
`optimization.vacuumHour: expected number, received undefined`. Only the
**top-level** keys became optional; the nested object still demands every field.
Fix: GET current settings, mutate the one field, PATCH the whole sub-object back.

### Dashboard APIs need a session cookie, not the service API key

Management routes use `isAuthenticated()` → `auth_token` cookie. A worker
`x-api-key` returns `AUTH_001 Authentication required`. Log in first:

```bash
curl -s -c /tmp/ck.txt -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' -d "{\"password\":\"$INITIAL_PASSWORD\"}"
curl -s -b /tmp/ck.txt "$BASE/api/settings/database"
```

---

## Part 2 — Base the branch on what you actually RUN

the operator's instruction, verbatim: _"don't use 3.8.49 - base it off what I am running
in production."_

**The deployed artifact's commit is frequently NOT the checkout's HEAD.** On the
router:

```
checkout HEAD:     6c26483d4   (package.json says 3.8.49)
deployed symlink:  current -> releases/standalone-<sha>
health endpoint:   "version":"3.8.50"
```

Three different answers. The one that matters is what the **running build** was
compiled from.

### Recipe: find the true production commit

```bash
# 1. what the service reports at runtime
curl -s "$BASE/api/monitoring/health" | grep -o '"version":"[^"]*"'

# 2. what artifact is actually symlinked
ls -la ~/src/App/current            # -> releases/standalone-<sha>
cat  ~/src/App/releases/*/BUILD_SHA 2>/dev/null

# 3. resolve that sha — it may not exist in the deploy checkout
git cat-file -t 2fc1229 || { git fetch fork; git fetch upstream; }
git log --oneline -1 2fc1229
git branch -a --contains 2fc1229    # -> remotes/fork/release/v3.8.50

# 4. branch from the EXACT sha, then confirm
git checkout -b feat/my-change 2fc1229fe
git rev-parse --short HEAD          # must equal the deployed sha
grep -m1 '"version"' package.json   # 3.8.50
```

**Pitfall:** the deployed sha may be absent from the production host's own
checkout (`fatal: ambiguous argument '2fc1229'`) because the artifact was built
in CI from a different branch. Fetch all remotes before concluding it's bogus.

### Verify the upstream repo — do not guess it

I added `upstream` as `agenthunt/the router` from memory. Wrong. Confirm with the
forge itself:

```bash
gh repo view <owner>/<repo> --json parent,name,owner
# -> "parent":{"owner":{"login":"diegosouzapw"},"name":"the router"}
git remote add upstream https://github.com/diegosouzapw/the router.git
git ls-remote --heads upstream | head    # prove it resolves
```

`package.json`'s `repository.url` is a second corroborating source. A wrong
upstream remote silently targets the wrong PR destination later.

### Know what your fork carries that upstream lacks

```bash
git log --oneline upstream/release/vX..fork/release/vX
```

Two fork-only commits here (a CI build workflow and a resilience fix). Those
must **not** leak into an upstream PR — branch from the shared base or cherry-pick
only your change.

---

## Part 3 — Tool quirk: `cronjob action='run'` consumes a one-shot

A job created with a one-shot ISO schedule (`repeat: once`) that has already
passed its fire time gets **deleted by `run` without executing**:

```
execution_success: false      # and the job vanished from jobs.json
```

Recover the prompt (a subagent had saved it to `/tmp/...-prompt.txt`), then
recreate with a real recurring cron expression before testing:

```
schedule: "0 9 * * 0"    repeat: forever
```

Then `run` executes properly (`execution_success: true`) and the job survives.

**Also:** a subagent asked to schedule something "~5 minutes from now" may take
longer than that to finish registering it, so the window closes before the job
exists. Prefer a recurring schedule plus an explicit manual `run` for validation.
