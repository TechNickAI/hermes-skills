# Native modules missing from a deploy bundle → silent slow fallback

**Class of failure:** a rebuilt artifact is missing a compiled native module.
The app does not crash. It falls back to a pure-JS/WASM implementation, keeps
answering health checks, and degrades in a way that surfaces days later as an
unrelated-looking error — here, `disk I/O error` on a button click.

Worked case: the router, 2026-08-11 cutover → symptom reported 2026-08-13.

## The shape

A CI artifact was cut over after passing every bundle assertion in the workflow.
It was missing three things the previous release had:

```
node_modules/better-sqlite3/build/Release/better_sqlite3.node   (compiled driver)
node_modules/bindings/                                          (better-sqlite3 requires it)
node_modules/file-uri-to-path/                                  (bindings requires it)
```

With no native driver the app fell through its driver ladder to **sql.js**
(SQLite compiled to WebAssembly), which holds the whole database in memory and
rewrites the entire file on persist. Against a 421 MB DB on a 1 GB tmpfs, writes
hit the ceiling and SQLite returned `disk I/O error`.

**2,092 disk I/O errors accumulated before a human noticed**, because the only
user-visible symptom was one dashboard button failing.

## Why the existing asserts missed it

The workflow asserted _feature strings_ present in the bundle
(`<OLD_FIX_SYMBOL>`, `<NEW_FLAG>`, the dbstat guard) and asserted
"some native modules exist":

```bash
if find .build -name "*.node" | head -1 | grep -q .; then
  echo "native modules present: $(find .build -name '*.node' | wc -l)"
```

The new bundle had **87** `.node` files versus the old one's 81 — more, not
fewer — so a count-based or existence-based check passes cleanly while the one
module that matters is absent. **Never assert "N native modules exist." Assert
the specific modules the app cannot run without, by path.**

Add to the artifact-verification step:

```bash
for m in \
  "node_modules/better-sqlite3/build/Release/better_sqlite3.node" \
  "node_modules/bindings" \
  "node_modules/file-uri-to-path" ; do
  if [ ! -e ".build/next/standalone/$m" ]; then
    echo "::error::missing required native dep: $m"; fail=1
  fi
done
# and prove it LOADS, not merely that it exists:
( cd .build/next/standalone && node -e "require('better-sqlite3')" ) \
  || { echo "::error::better-sqlite3 present but will not load"; fail=1; }
```

**A transitive dependency of a native module is part of the native module.**
`better-sqlite3/lib/binding.js` does `require('bindings')`; without that package
the compiled `.node` file on disk is dead weight and the error message you get
is `Cannot find module 'better-sqlite3'` — which reads like the package itself
is absent even though the directory is right there.

## Diagnosis: the driver ladder tells you before the symptom does

Grep the service log for the driver-selection lines at startup. A fallback
ladder announces itself:

```
[DB] Sync driver 'better-sqlite3' failed to open, will try next driver: Cannot find module 'better-sqlite3'
[DB] Sync driver 'node:sqlite' failed to open, will try next driver: Cannot find module 'node:sqlite'
[DB] Pre-initializing sql.js WASM (synchronous drivers unavailable)...
[DB] SQLite database ready: ...
```

That last line says **ready**. A health check passes. Only the three lines above
it reveal the app is running on its slowest, most memory-hungry rung. **After any
cutover, read the startup driver/engine selection lines, not just the ready
line.** Stack traces confirm it: the error frames named
`node_modules/sql.js/dist/sql-wasm.js`.

## Verifying the fix per PROCESS, not per file

`MainPID` may be a wrapper. On this service the systemd MainPID was
`/usr/bin/node dev/run-standalone.mjs` and the real worker was its child:

```bash
MAIN=$(systemctl --user show <svc> -p MainPID --value)
CHILD=$(pgrep -P "$MAIN" | head -1)
grep -o '/[^ ]*better_sqlite3\.node' /proc/$CHILD/maps | sort -u   # Linux
```

Checking the parent's maps reports zero mappings and looks like failure even
after a correct fix. Confirm the child. Also confirm `require` resolves from the
service's actual `WorkingDirectory` (`systemctl show -p WorkingDirectory`), since
Node resolution starts there:

```bash
cd "$(systemctl --user show <svc> -p WorkingDirectory --value)"
node -e "console.log(require.resolve('better-sqlite3'))"
```

## Prefer the bundle's own prebuild over a binary scavenged from the old release

Both work, but versions drift: the old release shipped better-sqlite3 **12.11.1**
and the new one **13.0.1**. Copying the old compiled `.node` into the new package
directory mixes an ABI with a JS wrapper it was not built against. The new
package already carried platform prebuilds:

```
prebuilds/linux-arm64.node  linux-x64.node  darwin-arm64.node  ...
cp prebuilds/linux-arm64.node build/Release/better_sqlite3.node
```

Match the platform to `uname -m` (aarch64 → `linux-arm64`), then prove it loads
and report the SQLite version it brings (`select sqlite_version()`), because that
version is a security-relevant fact in its own right.

## Sibling trap: the client tool is OLDER than the database

The system `sqlite3` CLI was **3.45.1**; the database was written by the app's
embedded **3.53.3**. The CLI could not read it, and said:

```
Error: in prepare, no such table: provider_connections
```

Not a version error. Not "unsupported format." It reports the tables as _missing_.
Any persistence/backup script built on the system CLI fails in a way that reads
like schema loss. **When a CLI reports a well-known table as absent, compare
`sqlite3 --version` against the writer's `select sqlite_version()` before
believing the schema is gone.** Fix: drive backups through the app's own
better-sqlite3 (`db.backup(path)`), not the distro CLI.
