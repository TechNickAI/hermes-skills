# Proving a fix is actually live after cutover

The deploy succeeded and health is green. That proves the _process_ booted. It
does not prove the _change you shipped_ is in the running code. These are
different claims and the second is the one the user cares about.

## When the obvious endpoint is unreachable

The natural verification — call the endpoint the fix repairs — often cannot be
done from a shell:

```
$ curl -H "x-api-key: $KEY" http://127.0.0.1:20128/api/settings/database
{"error":{"code":"AUTH_001","message":"Authentication required"}}   # 401
```

Dashboard/admin routes commonly authenticate with a **session cookie from a
password login**, not an API key. Read the route before concluding anything:

```ts
export async function GET(request: NextRequest) {
  if (!(await isAuthenticated(request))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    return NextResponse.json(getDatabaseSettings());   // <- the fixed code path
  } catch (error) {... 500... }
}
```

The auth gate fires **before** the repaired function is ever reached. So the 401
is not weak evidence, it is **zero** evidence — it says nothing about whether the
fix works. Do not report a 401 as "could not confirm the fix"; report it as "this
check cannot answer the question" and use a different one.

## The log-absence trap

The next instinct is to grep the journal for the error the fix eliminates:

```
dbstat errors since restart:   0
dbstat errors in prior 2h:     0     <-- also zero!
```

**Zero-after is meaningless when before is also zero.** Nobody had loaded the
settings page in either window. An absence-of-error comparison only carries
signal if the code path was actually exercised in both windows. Check the
baseline before citing the delta.

## What does work: read the compiled bundle

The deployed artifact is on disk. Grep the minified output for the guard and show
it in context:

```bash
CHUNK=$(grep -rlsF "no such (module|table): dbstat" \
  "$HOME/src/App/current/.build/next/standalone" | head -1)

python3 - "$CHUNK" <<'PY'
import sys
d = open(sys.argv[1], errors="ignore").read()
i = d.find("no such (module|table): dbstat")
print("..." + d[max(0,i-260):i+160].replace("\n"," ") + "...")
PY
```

Result — the single-probe helper and its guard survived minification intact:

```js
f = (function (a) {
  try {
    return (
      a
        .prepare("SELECT SUM(pgsize) as size FROM dbstat WHERE name = ?")
        .get("sqlite_master"),
      !0
    );
  } catch (a) {
    if (a instanceof Error && /no such (module|table): dbstat/i.test(a.message))
      return !1;
    throw a;
  }
})(a);
```

**Then run the same grep against the rollback target** to prove the strings
discriminate rather than matching everything:

```
NEW build: guard PRESENT
OLD build: guard ABSENT, unguarded 'FROM dbstat WHERE name' PRESENT
```

Present-in-new + absent-in-old is a real differential. Present-in-new alone
could just mean your grep is too loose.

Use `grep -rqsF` (fixed-string) for any pattern containing regex metacharacters —
`(module|table)` under plain `grep` is an alternation that matches nothing here.

## Verify provenance separately from behavior

Four independent facts, each catching something the others miss:

```bash
readlink -f ~/src/App/current                              # symlink → new release
systemctl --user show app -p MainPID --value               # PID changed
systemctl --user show app -p NRestarts --value             # 0 = clean, not crash-looped
curl -s.../health | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['system']['uptime'])"
```

A **small uptime** confirms a fresh process — a stale one would still be serving
the old code from memory-mapped files even after the symlink moved.
`NRestarts=0` distinguishes "started cleanly" from "crash-looped its way back to
active".

## Read redirects before calling them failures

```
/dashboard  http=307 -> /login     # NOT an error: auth redirect
curl -L     http=200, 629808 bytes, correct <title>, no error markers
```

A 307/302 on an authenticated page is normal. Follow it with `-L` and assert on
the final page's markup before reporting a UI problem.

## Watch for adjacent bugs the verification surfaces

Post-cutover checks legitimately reveal _other_ defects. Report them as separate
findings with their confidence level, not as deploy failures:

```
key_value.cacheSize = 65536      (persisted, 64 MB)
PRAGMA cache_size   = -16000     (live, 16 MB)
```

That mismatch was the _next_ PR's bug, confirmed in production. But the pragma
was read from a **fresh connection**, which gets the default rather than the
server's own session state — so it is consistent with the defect without being
conclusive. Say exactly that; do not upgrade "consistent with" into "proves".

Also expect memory figures to look dramatic and mean little: RSS 2.6 GB → 70 MB
across a restart is just a fresh process, not an improvement. Flag it as
unproven under load rather than claiming a win.

## Pitfall: `node -e` requiring a module resolves from CWD

```bash
node -e "require('better-sqlite3')"          # from $HOME → Cannot find module
cd "$HOME/src/App" && node -e "require(...)" # resolves
```

Earlier calls in the same session worked only because they happened to run from
the repo directory. When a verification script suddenly cannot find a module that
worked minutes ago, check the working directory before theorizing about the
database or the deploy. And when a retry loop fails all 10 attempts identically,
that is a **deterministic** error wearing a flaky error's clothes — read the real
message instead of adding more retries.
