# Verification that discriminates (or: why my fixtures agreed with my bug)

Worked case: the router v3.8.50 deploy, one occasion. Four CI builds (~15 min each)
burned iterating a release gate that kept **failing a correct artifact**.

## What happened

The deploy existed to fix a bundler bug: webpack replaced driverFactory's
injectable loader with its missing-module stub, so every SQLite driver reported
itself uninstalled and the app fell through to the sql.js WASM fallback.

I wrote a CI assert to prove the fix was in the bundle. Three revisions, three
FALSE FAILURES against a correctly built artifact:

| rev | assert                                                                                          | why it was wrong                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| v1  | real `require("better-sqlite3")` external must be in the same chunk as the driverFactory marker | the fix moves the literal `_require` calls into a new function, which webpack may place in a **different module** |
| v2  | no throw-stub in any file containing the driverFactory marker                                   | a stub module is a **generic webpack helper**; `middleware.js` carries one in the broken AND fixed bundle         |
| v3  | resolve the call site's binding, look up that module id                                         | webpack module ids are **global to the chunk graph**; looking only in the same file returned `UNKNOWN`            |

Every revision passed its own fixture tests. 18/18 green while the real artifact
failed.

## The actual lesson

**Fixtures written by the author of the code encode the author's mental model.
When the model is wrong, the code and the fixtures are wrong in the SAME
direction, so they agree with each other and both are wrong.** Green fixtures
are not independent evidence. They only prove internal consistency.

What finally exposed each error was running the check against a **real artifact
whose verdict was already known**.

## Rules

1. **Control-test every assert in BOTH directions against REAL artifacts**, not
   only fixtures:
   - known-BAD input (the currently deployed, broken bundle) must FAIL
   - known-GOOD input (the new artifact) must PASS
     An assert that has only ever seen one of the two is unvalidated. An assert
     that passes against both is decoration.
2. **Get the known-good artifact in hand before iterating a check against it.**
   I iterated a static check blind across four CI round-trips, guessing at the
   output shape. Download the artifact, or make the check PRINT the bytes it
   could not classify so the shape is learnable from one log instead of four.
3. **Do not gate a release on implementation internals when behaviour is
   testable.** Module ids, chunk layout, and minified shapes are the compiler's
   business and change without notice. What matters is whether the thing WORKS.
   Final design: the static check became **diagnostic only (never fails the
   build)**, and the gate became a real driver roundtrip — open a database,
   create a table, insert, read back, assert the value. That cannot be fooled by
   bundler internals.
4. **Fail closed.** Unresolvable binding, unknown module definition, zero call
   sites found → treat as BROKEN, never as OK.
5. **When an assert fails, ask "is the artifact wrong, or is my assert wrong?"**
   before touching the artifact. Here the build had been correct since the
   runner fix; every subsequent failure was my own verification. A second
   corroborating signal settles it — the bundle both shipped
   `prebuilds/linux-arm64.node` and **loaded SQLite 3.53.4** one line after my
   assert declared the binary "MISSING".

## Related trap: asserting a fixed path for a build output

The same session, the same step: I asserted
`node_modules/better-sqlite3/build/Release/better_sqlite3.node`. npm placed the
prebuilt binary at `node_modules/better-sqlite3/prebuilds/linux-arm64.node`.
The step reported `MISSING from bundle` immediately before successfully loading
the module. **Locate build outputs by search, not by a path you remember.**

## The cheap discriminator, when you do need a static check

Do not pattern-match file contents. Resolve what the CALL SITE actually invokes:
find `new (X("mod"))`, walk back to the binding `X = c(<id>)`, then classify
module `<id>` **across the whole graph**. Print the definition when it cannot be
classified.

## Demote every COPY of a bad check, not just the one in CI

Demoting the CI assert to diagnostic did not unblock the deploy: the same
false-BROKEN logic had been copy-pasted into the host-side staging script as a
hard `exit 1`, so staging aborted at step 4 for the identical wrong reason and
cost another round-trip. **When a check turns out to be wrong, grep the whole
tooling set for its text and fix every instance in the same pass** — CI
workflow, staging script, any local probe.

## Two traps in the RUNTIME proof itself

The behavioural gate is the right answer, but it has its own failure modes, and
both produced a false FATAL on a working artifact:

1. **Checking the wrong process for a `dlopen`.** `grep <module>
/proc/<pid>/maps` reported "not mapped" against a process that had loaded the
   module perfectly. The entrypoint (`dev/run-standalone.mjs`) is a **wrapper**
   that spawns the real server as a child; the child holds the database. Check
   the wrapper AND every descendant:

   ```bash
   CHECK_PIDS="$PID $(pgrep -P "$PID" | tr '\n' ' ')"
   for p in $CHECK_PIDS; do
     sudo grep -qE "<pkg>/(prebuilds|build)/[^ ]*\.node" /proc/"$p"/maps && MAPPED=1
   done
   ```

   On failure, PRINT every `.node` mapped in each pid — that output is what
   revealed the real filename.

2. **Grepping for the name you expect instead of the file that exists.** The
   prebuilt binary was `better-sqlite3/prebuilds/linux-arm64.node`, so
   `grep better_sqlite3.node` found nothing while the driver was demonstrably
   loaded. Match on the package directory plus `.node`, then echo what matched.

## Two independent signals beat one clever one

The verdict that finally settled it needed no bundler analysis at all — just the
same measurement on both processes, side by side:

```
live v3.8.49: wreq-js.linux-arm64-gnu.node ← no SQLite driver
staged v3.8.50: better-sqlite3/prebuilds/linux-arm64.node ← real dlopen

arrayBuffers: 1,326 MB live → 17 MB staged (76x)
DB file rewrites in 10s: ~5-9 live  →  0 staged
```

A before/after comparison on the SAME metric, across a known-bad and known-good
instance, is more convincing than any single static assert — and it is the
evidence the user actually wants in the report.
