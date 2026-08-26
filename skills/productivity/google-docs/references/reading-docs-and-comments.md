# Reading an existing Google Doc: full text + inline comments

This is the _read/review_ direction, distinct from the Markdown-import direction
documented in the main SKILL.md. Use this for meeting prep, reviewing a doc someone
else sent you, or synthesizing a document plus its unresolved comment threads.

## Native Google Doc (mimeType application/vnd.google-apps.document)

```bash
HOME=/Users/nick gog docs export <docId> --format txt --out /tmp/<name>/doc.txt
HOME=/Users/nick gog drive comments list <docId> --json > /tmp/<name>/comments.json
```

- `docs export --format txt` gives clean plain text. Read it with the `Read` tool
  (gives 1-indexed line numbers, useful for citing specific passages back to the user).
- `drive comments list --json` returns `{"comments": [...]}`, each with `author`,
  `content`, `resolved`, `quotedFileContent.value` (the anchored text), and a
  `replies` array (each reply has its own `author`/`content`/`createdTime`). This is
  where the real disagreement/debate in a doc usually lives — read every thread, not
  just the doc body.
- To find comments that `@mention` a specific person, search the raw JSON blob per
  comment (author tags don't reliably capture body `@mentions`); match on the
  mentioned email/name appearing anywhere in the comment or its replies.

## Word doc uploaded to Drive (mimeType.../wordprocessingml.document, i.e..docx)

Comments API returns an empty array for these even if the source doc had tracked
comments elsewhere — Drive's native comment thread only exists for files converted to
Google's own format. Check `mimeType` first with `gog drive get <id> --json` so you
know which path applies, then:

```bash
HOME=/Users/nick gog drive download <docId> --out /tmp/<name>/doc.docx
```

The `Read` tool auto-extracts `.docx` to numbered plain text (no separate
docx-parsing library needed, no need to `pip install python-docx`). Read it in
sequential offset chunks like any other long file; extraction preserves the outline
structure well enough to spot headings/tables inline.

## Workflow for meeting-prep / review tasks

1. Export text + list comments (native Doc) or download + Read (docx).
2. Read the whole thing before synthesizing — comment threads especially, since board
   memos and product docs often bury the real internal disagreement in a reply chain.
3. Cross-reference comment authors against known people/context (Cortex `people/`
   pages) so a synthesis can say who thinks what, not just quote anonymously.
4. Save the synthesis as a `ventures/` or `synthesis/` page in Cortex if this is
   recurring context (see the `cortex` skill), not just a chat reply.
