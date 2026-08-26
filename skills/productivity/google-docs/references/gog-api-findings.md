# gog CLI Empirical Findings (tested one occasion)

## Local version: v0.9.0

```
gog --version # Build: v0.9.0 (99d9575)
```

Upstream (steipete/gogcli) is at v0.29+ with much richer Docs editing. The
gap is significant. Always check `gog docs --help` before relying on Docs
editing subcommands.

## Capability matrix (v0.9.0)

| Service      | Capability in v0.9.0                                                                        | Notes                                        |
| ------------ | ------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `gog docs`   | create (title only), export, info, copy, cat                                                | No `docs write --markdown`, no `docs format` |
| `gog sheets` | create, get, update, append, clear, format, metadata, export                                | Full CRUD + cell formatting                  |
| `gog slides` | create (title only), export (pdf/pptx), info, copy                                          | No content authoring                         |
| `gog drive`  | ls, search, get, download, upload, mkdir, delete, move, rename, share, unshare, permissions | No `--convert` flag for Drive import         |

## Auth notes

- Config lives at `~/Library/Application Support/gogcli/` on macOS.
- `gog auth list --plain` → tab-separated: `email\tclient\tscopes\tdate\tauth-method`
- `gog auth tokens export <email> --output <file> --force` → writes JSON with `refresh_token` key.
- `gog auth tokens export --output -` does NOT stream to stdout in v0.9.0; it tries to open `-` as a literal filename. Always use a temp file.
- `gog` does NOT support `--home` in v0.9.0 (`unknown flag --home`). Pass `GOG_HOME` via subprocess env instead.
- gog `--client` flag selects a named OAuth client (stored credentials + token bucket).

## gog sheets pitfalls

- `gog sheets update SID RANGE '[[...]]'` with a JSON string as the positional arg treats it as a flat single-column. **Always use `--values-json`.**
- `--input USER_ENTERED` required for numbers/formulas to be typed values, not text strings.
- `gog sheets create --json | python3 -c "import json,sys;..."` — add `2>/dev/null` to suppress gog progress noise on stdout from corrupting JSON parse.

## Drive convert-on-upload paths

Tested against Google Drive API v3 multipart upload with target mimeType:

| Source file | Source MIME                                                     | Target MIME                                | Result                                               |
| ----------- | --------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------- |
| `.md`       | `text/markdown`                                                 | `application/vnd.google-apps.document`     | ✅ Native Doc, headings/tables/code preserved        |
| `.docx`     | `application/vnd.openxmlformats-...wordprocessingml.document`   | `application/vnd.google-apps.document`     | ✅ Native Doc, but code blocks degraded vs. markdown |
| `.csv`      | `text/csv`                                                      | `application/vnd.google-apps.spreadsheet`  | ✅ Native Sheet                                      |
| `.xlsx`     | `application/vnd.openxmlformats-...spreadsheetml.sheet`         | `application/vnd.google-apps.spreadsheet`  | ✅ Native Sheet                                      |
| `.pptx`     | `application/vnd.openxmlformats-...presentationml.presentation` | `application/vnd.google-apps.presentation` | ✅ Native Slides                                     |
| `.md`       | `text/plain` (wrong)                                            | any                                        | ❌ 400 Bad Request                                   |

**Winner for Docs:** direct `.md` → `text/markdown` import. Preserves inline code, fenced code blocks with language tags, tables, and all standard formatting elements better than the docx route.

## API supportsAllDrives

These endpoints require `supportsAllDrives=true` to work with Shared Drive files:

- `files.create` (upload, mkdir)
- `files.get` (meta)
- `files.export`
- `permissions.create` (share)

Without it, Shared Drive parents are treated as unsupported. The `gworkspace.py`
helper applies it to all five as of PR #52.

## gworkspace.py argparse pattern

Credential flags (`--refresh-token-file`, `--client-secret-file`, `--gog-client`,
`--gog-home`, `--gog-account`) must be accepted both **before** and **after** the
subcommand.

Correct pattern (PR #52):

- Use a shared parent `ArgumentParser(add_help=False)` with `default=argparse.SUPPRESS`.
- Attach it as `parents=[creds]` to both root and every subparser.
- `SUPPRESS` prevents a subparser parse from overwriting root-set values with `None`.
- Read all credential attrs via `getattr(args, "attr_name", None)`.

Wrong pattern (previous): putting args only on root parser means `--flag after subcmd` fails. Putting args on subparsers without `SUPPRESS` means the subparser overwrites root-set values with `None`.
