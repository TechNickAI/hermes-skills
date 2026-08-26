# Pre-PR Multi-Review Findings (one occasion)

Panel: Grok (contrarian/security) + Gemini (coverage) + GPT (structure/trigger clarity)

## What the panel caught before PR opened

### High / critical (all fixed before first push)

- **Missing prerequisites section** (GPT HIGH, Gemini MED) — skills assumed gog,
  python3, and pandoc were present. Added `## Prerequisites` to all three skills.

- **Credential flags only accepted before subcommand** (GPT MED, addressed in
  follow-up PR #52) — `--refresh-token-file` was root-parser-only, so
  `gworkspace.py token --refresh-token-file F` failed silently. Fix: shared
  parent parser with `argparse.SUPPRESS` defaults.

- **gog binary PATH injection risk** (Grok HIGH) — bare `["gog",...]` in
  subprocess allows PATH hijack. Fix: `shutil.which("gog")` before every call.

- **Credential file ownership/mode not checked** (Grok HIGH/MED) — added
  ownership + 0o077 mode check via `_read_secret_json`.

- **Credential search breaks on first file even if partial** (Gemini MED,
  Cursor caught again post-merge) — loop `break` on first existing file regardless
  of whether keys resolved. Fix: continue until both `client_id` + `client_secret`
  found.

- **`md2googleslides` path oversold** (all 3) — presented as a first-class option;
  it can prompt interactively on first use. Marked optional/pre-authed-only.

- **`share` command irreversible, undocumented** (Gemini MED) — added explicit
  approval gate and doc block.

- **`open()` without `with` blocks** (Gemini LOW) — fixed; all file handles now
  context-managed.

- **Nested fenced code block in Docs skill broke Markdown rendering** (Gemini MED)
  — switched outer fence to tildes (`~~~`).

### Wontfix / false positives from the panel

- Slides `decode('utf-8', 'ignore')` → changed to `'replace'` (Gemini LOW, valid).
- `gog sheets create` stdout JSON parsing without `2>/dev/null` → added redirect.

## Panel effectiveness notes

- All three families found different things: Grok led on security/credential handling;
  Gemini led on cross-skill consistency and coverage gaps; GPT led on argparse and
  trigger clarity.
- Total: ~12 real pre-PR fixes applied, zero false positives accepted.
- Post-PR bots (Cursor, Codex) found 5 more over 2 PRs — all were either stale
  re-anchors or genuinely new issues caught after merge. See `github-pr-workflow`
  pitfall on post-merge findings.
