# Nested bundle staleness, and the control test that catches a lying probe

Worked case: the router, one occasion. A dashboard provider (`xai-oauth`)
was "missing" from a live service for ~3 weeks. Nothing was deleted, nothing was
misconfigured, and every obvious version signal read as current.

## 1. The artifact contains a nested copy of itself — and the nested one is served

The standalone tarball unpacks to TWO complete Next.js bundles:

```
<release>/.build/next/                            BUILD_ID ef-naVy3Rd6gd2YcFlrUn   (Aug 3)
<release>/.build/next/standalone/.build/next/     BUILD_ID aqoF-Ldw-n08SEFVDvPta   (Jul 19)  <-- SERVED
```

systemd's `WorkingDirectory` points at the **nested** path, so the nested bundle
is what users actually get. The assembly step (`assembleStandalone.mjs`, invoked
by `build-next-isolated.mjs`) can leave that nested copy STALE while the outer
one rebuilds cleanly. Result: an August release serving July UI code.

**Why it hides so well.** Every independent signal you would normally trust
reads correct:

| signal                               | reported             | reality                         |
| ------------------------------------ | -------------------- | ------------------------------- |
| release dir name / mtime             | Aug 3                | outer bundle only               |
| `/api/monitoring/health` version     | current              | server code, not UI chunks      |
| deployed git commit source           | contains the feature | never reached the served bundle |
| a _different_ feature merged earlier | present and working  | predates the stale cut          |

That last row is the cruel one: a sibling feature merged before the stale
bundle's build date works perfectly, which "proves" the deploy is fine. In this
case `grok-cli` (merged Jun 27) rendered while `xai-oauth` (merged Jul 19,
03:18 — hours after the stale bundle was built) did not.

**Diagnostic — compare BUILD_ID at both levels.** One command settles it:

```bash
for d in "$REL/.build/next" "$REL/.build/next/standalone/.build/next"; do
  printf '%s -> ' "$d"; cat "$d/BUILD_ID"; echo
done
```

Equal = fine. Different = the served bundle is stale, full stop. Add this to the
post-cutover checklist for any Next.js `output: "standalone"` deploy.

**Fix.** No rebuild needed if a good CI artifact exists: re-extract the SAME
artifact into a NEW release dir, confirm both BUILD_IDs now match, stage, swap
the symlink. Re-extraction fixes it because the artifact was always correct —
only the on-host unpack/assembly had drifted.

Generalize the class: **any deploy artifact that embeds a nested copy of its own
runtime assets can serve the nested copy while you inspect the outer one.**
Verify the path the process actually reads, not the path that shares its name.

## 2. A presence check that also fires on a known-bad control is worthless

The first probe was `grep 'Provider not found'` on the provider page. It
returned a hit, and that was reported as evidence the provider was gone.

It was a false positive. The route is a client-rendered shell: **every**
`/dashboard/providers/<id>` request returns the same 629,808-byte HTML
containing that literal string, before hydration decides what to render.

Running the control made it obvious in one shot:

```
grok-cli             notfound_hits=1   bytes=629808   <- known GOOD
xai-oauth            notfound_hits=1   bytes=629808   <- suspect
claude               notfound_hits=1   bytes=629808   <- known GOOD
codex                notfound_hits=1   bytes=629808   <- known GOOD
bogus-provider-xyz   notfound_hits=1   bytes=629808   <- known BAD
```

Identical output for a valid provider and a provider that cannot exist. The
probe had zero discriminating power. Byte-identical response sizes across all
five are themselves the tell — if a "difference" test returns the same length
for every input, it is not measuring the thing you named.

**The honest probe for client-rendered pages:** fetch the page, extract the JS
chunks it references, and grep _those_.

```bash
curl -sL "$BASE/dashboard/providers/xai-oauth" -o /tmp/pg.html
grep -oE '/_next/static/chunks/[^"]+\.js' /tmp/pg.html | sort -u > /tmp/chunks.txt
while read -r c; do
  curl -s "$BASE$c" | grep -q 'xAI OAuth (Grok)' && echo "HIT $c"
done < /tmp/chunks.txt
```

This separated the states cleanly and became the cutover gate:

```
LIVE   (before fix)   26 chunks, 0 containing the provider
STAGED (corrected)    27 chunks, 1 containing it
LIVE   (after swap)   1 chunk  — plus the authHint string rendering
```

### Rules this produces

- **Run every presence/absence probe against a known-GOOD and a known-BAD
  control before believing it.** Two controls, not one. If good and bad return
  the same answer, the probe is broken — fix the probe before touching the
  subject. This costs one extra command and would have saved a wrong diagnosis
  reported to the user.
- **Never diagnose a client-rendered SPA from its server HTML.** The HTML is a
  shell; strings like "not found", "loading", and error copy are present for
  every route regardless of state.
- **Prefer a probe whose output differs in KIND, not degree.** "0 chunks vs 1
  chunk" is decisive. "contains a string that is always there" is not.
- **When you have already reported a wrong finding, correct it plainly and
  first**, before presenting the real result. Say which check was bad and why.
  Do not quietly replace it with the good one.

## 3. Staging notes that mattered

- Verify the artifact's own integrity before shipping: the downloaded CI
  artifact's `sha256` matched the on-host copy byte-for-byte, which rules out
  transfer corruption as a cause and makes "re-extract" a safe move.
- Rehearse migrations on a **copy** of the DB and diff the tables that the
  destructive migrations touch. Here: `provider_connections` 16 → 16 with
  identical per-provider counts, `key_value` 494 → 495. Non-destructive,
  confirmed before cutover rather than hoped for after.
- Prove the live service is untouched _while_ staging: `MainPID` unchanged and
  health still 200 on the live port during the whole test-port run.
- Confirm the restart actually took by **PID change** (`415256 → 463860`), not
  by `is-active`.

## 4. Shell traps hit while building the probes

- `find... | head -3 | while read` — `head` closing the pipe kills `find` with
  SIGPIPE and the script exits **141**, aborting a `set -e` run midway. Write
  results to a temp file first, then loop over the file.
- `find <no matches> | xargs file` runs `file` with zero arguments, which prints
  its full usage block to stdout and pollutes the report. Guard with `-r` or
  check the file list is non-empty.
- Large inline heredocs sent through the terminal tool can trip H‍ermes' hardline
  command-parser block. The reliable pattern for anything non-trivial on a
  remote host: `write_file` locally → `scp` → `ssh host 'bash /tmp/script.sh'`.
  This also makes each probe re-runnable and diffable instead of retyped.
