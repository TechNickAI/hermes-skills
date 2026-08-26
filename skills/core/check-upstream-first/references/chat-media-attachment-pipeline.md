# Telegram MEDIA: Attachment Delivery — CLOSED ≠ FIXED Worked Example

Source-verified 2026-08-03 against `NousResearch/hermes-agent` `main`.
A concrete worked example of Step 3c (CLOSED ≠ FIXED) and Step 3 (search
upstream before reading source) applied to the Telegram outbound attachment
pipeline.

## The symptom class

"Agent sends `MEDIA:/path/to/file.py` on Telegram but the file doesn't arrive
as an attachment — only the text message is delivered." Or: ".md files not
delivered." Or: "only the first of multiple MEDIA: tags is attached."

## What happened (the CLOSED ≠ FIXED trap)

Five issues documented the same attachment-delivery failure class:

| Issue  | State                | Labels                                                   |
| ------ | -------------------- | -------------------------------------------------------- |
| #34517 | closed               | .md silently dropped                                     |
| #42206 | closed               | .py files not delivered, multiple MEDIA only first works |
| #35474 | closed (dup)         | .markdown not delivered                                  |
| #6249  | closed (not_planned) | image path echoed as text                                |
| #62079 | **OPEN**             | transient upload failures → permanent loss, no retry     |

Five PRs were opened to fix these:

| PR     | State  | Merged?              |
| ------ | ------ | -------------------- |
| #34022 | closed | ✅ merged 2026-05-28 |
| #42226 | closed | ❌ NOT merged        |
| #42374 | closed | ❌ NOT merged        |
| #60069 | closed | ❌ NOT merged        |
| #6254  | closed | ❌ NOT merged        |
| #36060 | closed | ❌ NOT merged        |

**The trap:** Issues #42206, #35474, #6249 were all closed by teknium1 on
2026-07-12/16 — but NOT via a merged PR. The cross-referenced PRs (#42226,
#42374, #60069) were all closed without merge. Commits `8713444a` and
`6622289a` appeared in the issue timeline but are NOT on `main` (diverged,
behind by 5672 commits).

**The actual fix:** PR #34022 (merged 2026-05-28) addressed the root cause
differently — instead of adding more extensions to `MEDIA_DELIVERY_EXTS`, it
changed `validate_media_delivery_path()` to a denylist-based model and added
`MEDIA_EXTENSIONLESS_TAG_RE` as a validation-gated fallback. So `.py` files
ARE deliverable on current `main`, but via the validation fallback (file must
exist on disk + pass denylist), NOT via the fast-path extension match.

## How to verify (the authoritative check)

```bash
# 1. Is the fix PR actually merged?
gh api repos/NousResearch/hermes-agent/pulls/34022 --jq '{state,merged,merged_at}'

# 2. Is the fix on main?
gh api "repos/NousResearch/hermes-agent/compare/main...<sha>" --jq '{status,ahead_by,behind_by}'
# "behind" = commit is an ancestor of main (good)

# 3. Does the code actually contain the fix symbols?
# Fetch base.py from main and grep for MEDIA_EXTENSIONLESS_TAG_RE
```

## The pipeline (for diagnosing future attachment issues)

Three stages: **extraction** → **validation** → **dispatch**.

### Extraction (`gateway/platforms/base.py:4438`)

`extract_media(content)` uses two regexes:

1. `MEDIA_TAG_CLEANUP_RE` (base.py:1699) — fast path for known extensions in
   `MEDIA_DELIVERY_EXTS` (base.py:1639).
2. `MEDIA_EXTENSIONLESS_TAG_RE` (base.py:1735) — validation-gated fallback
   for unknown extensions / extensionless files. Calls
   `validate_media_delivery_path()`.

Protected spans (code blocks, inline code, JSON string values) are masked —
tags inside them are never extracted.

### Validation (`gateway/platforms/base.py:1448`)

`validate_media_delivery_path(path)`:

- Default mode: accept any existing file not under the denylist.
- Denylist: `/etc`, `/proc`, `/sys`, `/dev`, `/root`, `/boot`, `/var/log`,
  `/var/lib`, `/var/run`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`,
  `~/.docker`, `~/.config`, `~/.azure`, `~/.gcloud`, `Library/Keychains`.
- Strict mode (`HERMES_MEDIA_DELIVERY_STRICT=1`): file must be under a
  Hermes cache dir, `HERMES_MEDIA_ALLOW_DIRS`, or freshly produced.

### Dispatch (`tools/send_message_tool.py:1176` for standalone;

### `gateway/run.py` for gateway path)

Extension → Bot API method:

- Images → `send_photo` (or `send_document` if `[[as_document]]`)
- Video → `send_video`
- Voice (.ogg/.opus + is_voice) → `send_voice`
- Audio (.mp3/.m4a) → `send_audio`
- Everything else → `send_document`

Base `send_document` fallback (base.py:4213): sends `⚠️ Couldn't deliver the
file attachment.` — does NOT echo the host path.

## `MEDIA_DELIVERY_EXTS` on current main

```
Images: .png .jpg .jpeg .gif .webp .bmp .tiff .svg
Video: .mp4 .mov .avi .mkv .webm .3gp
Audio: .mp3 .m2a .wav .ogg .opus .m4a .flac
Documents: .pdf .docx .doc .odt .rtf .txt .md .epub
Data: .xlsx .xls .ods .csv .tsv .json .xml .yaml .yml
Geo: .kmz .kml .geojson .gpx
Presentations: .pptx .ppt .odp .key
Archives: .zip .tar .gz .tgz .bz2 .xz .7z .rar .apk .ipa
Web: .html .htm
```

**NOT in list (deliverable via validation fallback only):** `.py`, `.js`,
`.ts`, `.sh`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.css`, `.sql`, `.toml`,
`.ini`, `.cfg`, `.log`, `.markdown`, and all extensionless files.

## Still-open issues

- **#62079** (OPEN, P2): Transient Telegram upload failures (`httpx.ReadError`,
  `TimedOut`) fall through to base `send_document` → `⚠️` notice with no retry.
  No Bot API fallback, no structured failure result.
- **#60845** (OPEN, P2): Queued follow-up responses bypass `extract_media()`
  entirely → `MEDIA:` tags appear as plain text.

## Sending contract for agents

1. `MEDIA:/absolute/path/to/file.ext` — one tag per line.
2. Prefer `MEDIA_DELIVERY_EXTS` extensions for fast-path extraction.
3. Code files / `.log` / extensionless: write file first, verify exists, then
   emit tag — delivery goes through validation fallback.
4. Never put `MEDIA:` inside code blocks / inline code / JSON strings.
5. Never glue tags: `MEDIA:/a.pngMEDIA:/b.png` — use newlines.
6. Docker terminals: emit host-visible path, not container-internal path.
7. Transient upload failures cause permanent loss (no retry, #62079 open).
