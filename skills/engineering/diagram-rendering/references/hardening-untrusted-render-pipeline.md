# Hardening the diagram-render pipeline (session-derived, 2026-07-21)

Context: shipping `diagram-rendering` through a full code-change-workflow PR
(TechNickAI/agent-skills #1) put `scripts/render.py` through a multi-review panel
plus **five rounds** of Cursor Bugbot. Each round's findings got smaller — a good
convergence signal. This file records the concrete defects so a future session
building or auditing a "fetch-render-rasterize untrusted output → image" pipeline
starts already knowing them. All were verified against real code, not accepted blind.

## The security spine (do these or the pipeline is unsafe)

1. **Untrusted SVG + headless Chromium = SSRF surface.** `--disable-javascript`
   only kills `<script>`. Declarative external refs still fetch during raster:
   `<image href="https://…">`, `<use href>`, CSS `url(https://…)`.
   Fix = **fragment allowlist**: neutralize any `href`/`xlink:href`/`src`/`url()`
   value that does not start with `#`. Must handle:
   - quoted form: `href="…"`
   - unquoted form: `href=…` (valid in HTML/SVG parsers, a denylist regex misses it)
   - absolute/relative paths (`/etc/passwd`, `../secret`) — a scheme denylist
     (`https?:|file:|//`) does NOT catch these; the allowlist does.
     Unit-test it: feed a synthetic SVG mixing `evil.example`, `/etc/passwd`,
     `../x`, `//host`, and a legit `#grad1`; assert all externals blanked, `#frag` kept.

2. **`file://` construction.** Use `pathlib.Path(p).as_uri()`, never
   `f"file://{p}"`. Paths with spaces/reserved chars silently produce an invalid URL
   → Chromium renders nothing. Verified by rendering into `~/dir with spaces/a b.png`.

3. **Write-verify-replace ordering.** Render/download to a `mkstemp` temp under
   `$HOME`, verify it's a real non-blank PNG, THEN `os.replace()` onto `--out`.
   - Verifying AFTER replacing means a blank render deletes a pre-existing good file.
   - A predictable `out+'.part'` opened with plain `open()` follows a pre-planted
     symlink → attacker-chosen write target. `mkstemp` (random name) closes this.
   - In the `finally` cleanup, guard with a `replaced` flag: after a _failed_
     `os.replace` the temp holds the only good render — deleting it in `finally`
     leaves the user with no output and a traceback. Only unlink if NOT replaced.

4. **`$HOME` confinement must resolve symlinks.** A lexical `abspath().startswith($HOME)`
   is bypassable by a symlink under `$HOME` pointing out. Resolve the parent with
   `realpath` + compare via `os.path.commonpath`, and reject a final component that is
   itself a symlink.

5. **Base-URL config is trusted, input is not.** `KROKI_BASE`/`QUICKCHART_BASE`:
   validate `http(s)` scheme, treat as operator config, never derive from a prompt.
   Bound network reads (`read(MAX+1)`) and input file sizes; clamp width/height/scale.

## The blank-render check (subtle)

- Verify PNG magic bytes first; a render host error returns an HTML/text body, not a PNG.
- With Pillow: `Image.verify()` + count non-background samples.
- **Two calibration bugs found by review:**
  - `distinct < 3` rejects a legitimate 2-color image (background + one ink). A
    minimal chart is exactly 2 colors. Gate on `distinct < 2`.
  - An **absolute** `nonbg < 20` floor plus a **coarse** step-7 sample grid can
    false-positive: a thin stroke / sparse 2-node diagram falls between samples.
    Fix = fine sample grid (step 3) so thin strokes can't hide, AND a **proportional**
    floor `max(1, int(sampled * 0.0005))` so tiny valid renders pass while a large
    truly-blank canvas still fails.
- Honesty: without Pillow you only have PNG-magic + a weak size heuristic — a large
  blank canvas can exceed 2KB. Document that the guard catches _blank_, not _wrong_,
  and tell the caller to eyeball anything owner-facing.

## Kroki operational reality

- **Mermaid renderer is load-flaky.** Intermittent HTTP 400 body
  `"Failed to launch the browser process"` = a crash inside Kroki's _own_ headless
  browser. The identical request 400s N times then 200s seconds later; curl vs urllib
  is irrelevant. Add a small retry on transient 5xx + that specific 400.
- **D2 is SVG-only** on hosted Kroki (PNG endpoint 400s). Fetch SVG, rasterize locally.
- Rasterizing SVG for **all** languages (not just D2) is worth it: it makes the 2×
  scale + `--width/--height` flags apply uniformly, instead of only on the D2 path.

## Process notes that paid off

- **Automated PR bots respond in ~1–2 min and find real bugs.** Poll the PR directly
  (`gh api …/pulls/N/comments`) rather than only waiting on a dispatched review.
- **Verify each bot claim against the real code before fixing.** One "stale" SVG-fetch
  finding kept re-anchoring to the original commit line across rounds; it was already
  fixed — don't re-fix, mark resolved. Reply + 👍-react + let the bot re-review until
  its check flips to `pass`, then merge.
- Multi-review panel degraded to single-model-family (a reviewer seat's sandbox failed
  to launch) — disclose that honestly in the PR body; don't imply a full panel ran.
