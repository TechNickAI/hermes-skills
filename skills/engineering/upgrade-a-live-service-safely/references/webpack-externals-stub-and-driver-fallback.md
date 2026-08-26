# The webpack "missing module" stub: a native driver that silently degrades

Worked case one occasion, the router. Symptom presented as **four unrelated
problems**; all four were one bundling defect.

## Fingerprint

The app logs a module as missing while the module is demonstrably on disk:

```
[DB] Sync driver 'better-sqlite3' failed to open, will try next driver: Cannot find module 'better-sqlite3'
[DB] Sync driver 'node:sqlite'   failed to open, will try next driver: Cannot find module 'node:sqlite'
[DB] Pre-initializing sql.js WASM (synchronous drivers unavailable)...
```

Meanwhile, from the app's own working directory:

```bash
cd <standalone> && node -e "console.log(require('better-sqlite3'))"   # works fine
```

**A missing native module usually does not crash the service.** It falls through
to a slower pure-JS/WASM fallback that looks healthy for days, then surfaces as
something that sounds like a different bug entirely.

## The cause

Bundlers only treat a require as an _external_ when they can read the module id
as a **literal at the call site**. Given an injectable loader:

```ts
const _require = createRequire(import.meta.url);
createSyncDriverFactory(_require); // loader passed as a VARIABLE
//...later, inside the factory:
load("better-sqlite3"); // unanalyzable
```

webpack cannot see what `load` is, so it replaces **the loader itself** with its
missing-module stub. Compiled output:

```js
570591: a => {
  function b(a) {
    var b = Error("Cannot find module '" + a + "'");
    throw b.code = "MODULE_NOT_FOUND", b;
  }
  b.keys = () => [], b.resolve = b, b.id = 570591, a.exports = b
}
```

A function whose only behavior is to throw. Every driver in the cascade calls it,
every one "fails," and the code falls through to the last-resort driver.

## Diagnosis: four steps, in this order

Do NOT stop at step 1 — a naive grep produces the OPPOSITE conclusion.

**1. Count real externals vs. stub text — and do not confuse them.**

```bash
grep -rhoF 'require("better-sqlite3")' --include=*.js.build | wc -l # 726 (!)
```

726 real requires looks like proof the bundle is fine. It is not. Most live in
vendored `node_modules` copies, and the string `Cannot find module 'x'` also
appears in ordinary **error-classification** code
(`b.includes("Cannot find module 'better-sqlite3'")`), which is not a stub.
Classify each hit; never count.

**2. Find the chunk that actually holds the calling code**, via a distinctive
marker string from the source (an error message, a comment):

```bash
grep -rlF "Nenhum driver SQLite" --include=*.js.build
# .build/next/server/chunks/12718.js, 1716.js, middleware.js
```

**3. Read the call site and identify the require function.**

```js
let l = (d = c(570591), function(a,b){... new (d("better-sqlite3"))(a,b)... })
```

`d` is **webpack module 570591**, not `createRequire`. Confirm the chunk has no
real external of its own:

| file              | real `require("x")` externals | `new(d("x"))` call sites |
| ----------------- | ----------------------------: | -----------------------: |
| `chunks/12718.js` |                         **0** |                        1 |
| `chunks/1716.js`  |                         **0** |                        1 |
| `middleware.js`   |                 1 (id 487550) |                        1 |

A healthy external looks like `487550: a => { a.exports = require("better-sqlite3") }`.
Its presence in _one_ file proves nothing about the chunk that does the calling.

**4. Print the definition of the referenced module id.** This is the decisive
step and the only one that yields a yes/no. If it is the throwing stub above,
the diagnosis is closed.

## Rule out the boring causes first

Before blaming the bundler, prove the module is genuinely reachable — otherwise
you will "fix" a build defect that was really a deploy/layout problem:

```js
// resolve from EVERY plausible anchor, not just cwd
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");
for (const anchor of [entrypoint, serverJs, middlewareJs, theChunk]) {
  try {
    console.log(
      createRequire(pathToFileURL(anchor).href).resolve("better-sqlite3"),
    );
  } catch (e) {
    console.log("FAILS", e.code);
  }
}
```

If every anchor resolves and the `.node` binary loads by hand, the filesystem is
innocent and the compiled code is the defect.

Beware a false negative here: running the probe from `/tmp` reports
`Cannot find module` purely because of Node's upward `node_modules` walk. **Run
resolution probes from the app's real working directory**, or you will
manufacture evidence for the wrong theory.

## The fix

Keep the module name a **literal string at each call site** so static analysis
can see it:

```ts
function requireSqliteDriver(moduleName: string): unknown {
  switch (moduleName) {
    case "bun:sqlite":
      return _require("bun:sqlite");
    case "better-sqlite3":
      return _require("better-sqlite3");
    case "node:sqlite":
      return _require("node:sqlite");
    default:
      throw new Error(`Unsupported SQLite driver module: ${moduleName}`);
  }
}
```

Hoisting the literals into a constant or a map keyed by a variable **re-breaks
it**. The switch looks redundant; it is load-bearing.

## Why unit tests never catch this

`tsx` / `node --test` resolve the injected `_require` normally, so the cascade
works and the tests pass **either way**. The defect exists only in a real
production webpack build. Any assertion must run against the **packaged
artifact**, not the source tree — see `native-module-completeness-in-bundles.md`
for the by-path assertions, and add a boot-log assertion that the intended
driver was selected.

## Do not inherit a root cause from a PR description

The whole diagnosis above was available in an existing PR writeup, and I
repeated it to the user as established fact for several turns — "the bug is
already identified" — without having verified a single claim in the deployed
artifact. the operator pushed back: _"what do you mean the bug has already been
identified?"_ Running the four steps then produced a **materially more precise**
answer than the one I had been repeating: I had been saying webpack "stubbed the
require", when it actually replaced **the loader function itself**, and the
`middleware.js` external I would have cited as proof of health belongs to
unrelated call sites.

A PR body, an issue thread, or a previous session's conclusion is a **hypothesis
with a citation**, not evidence. Restate it as "PR #10 claims X; I have not
confirmed it against the running build", then confirm it before it becomes the
basis for a production change. The confirmation here took minutes and improved
the fix's assert.

## Downstream symptoms this one defect produced

Worth internalizing, because each was independently plausible as its own bug:

| observed                                                 | actual mechanism                                             |
| -------------------------------------------------------- | ------------------------------------------------------------ |
| "memory leak", `external`/`arrayBuffers` climbing to GBs | fallback serializes the WHOLE DB to an ArrayBuffer per write |
| ~216 MB/s sustained disk writes, EBS burst credits at 0% | same serialization reaching disk                             |
| backups randomly `SQLITE_CORRUPT`                        | readers catching the file mid-rewrite (torn read)            |
| latency creeping up between restarts                     | GC pressure from the discarded buffers                       |

**The tell:** `heapUsed` stays flat while `external`/`arrayBuffers` climbs in
steps matching the database file size. That is whole-object serialization, not a
JS heap leak. Sample `/api/monitoring/health` (or `process.memoryUsage()`) every
10s and compare the step size against `stat -c%s <dbfile>`:

```
14:04:39  arrayBuffers= 498M   dbfile=418M
14:04:50  arrayBuffers= 884M   dbfile=418M   <- +386M
14:05:30  arrayBuffers=1326M   dbfile=418M   <- +442M
```

A watchdog looking at RSS alone will call this "a C++ addon or streaming buffer
leak" and escalate repeatedly for a permanent code fix that already exists.
