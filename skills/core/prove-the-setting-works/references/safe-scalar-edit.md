# Safe single-scalar YAML edits — ruamel pitfalls & diff-gate fallback

When a verified lever must be rolled out across many fleet `config.yaml`
files, the edit has to stay a one-line, reviewable change. `ruamel.yaml` will
try to churn the file in ways that hide your edit, beyond the well-known
80-column width reflow.

## Pitfall 1 — ruamel re-indents block sequences globally

ruamel applies ONE global `y.indent(sequence=…, offset=…)` to the whole
document. The default (`sequence=4, offset=2`) turns **indentless** block
sequences (`- item` at the parent's indent) into indented ones (`  - item`)
— and vice-versa if you set it the other way. A single scalar edit then churns
_every_ list in the file (fallback_providers, toolsets, disabled,
reference_models, …), producing a huge spurious diff.

**Detect before dumping (from the backup text):**

```python
if any(line.startswith("  - ") for line in source_text.splitlines()):
    y.indent(mapping=2, sequence=4, offset=2)   # file uses indented sequences
else:
    y.indent(mapping=2, sequence=2, offset=0)   # file uses indentless sequences
```

## Pitfall 2 — ruamel unfolds multi-line scalars

Even with `width=4096`, ruamel collapses a folded / multi-line scalar onto one
line (e.g. a multi-line `system_prompt: >` block, or a long single-quoted
string). Setting `y.fold_pos = 4096` does NOT preserve already-folded
presentation. A one-key change then rewrites an unrelated long `system_prompt`
as a single 600-char line.

## Recovery — diff-gate + text-surgical fallback (the reliable path)

When ruamel insists on churning, **gate it and fall back** rather than shipping
a noisy diff:

1. Compute a unified diff of candidate vs backup.
2. **Present-value case** (changing `key: old` → `key: new`): the diff MUST be
   exactly one `- ` line and one `+ ` line, both containing `key:`. Larger =
   ruamel churned something → **restore the backup** and switch to text-surgical.
3. **Absent-key case** (adding the key): exactly one `+ ` line containing `key:`,
   zero `- ` lines.
4. **Text-surgical fallback (present case):** find the parent block (`agent:`),
   locate the unique `  key:` line within it, replace only the value (preserve
   any trailing ` # comment` and the original EOL), rewrite. Re-parse with
   ruamel to confirm the value landed and the file still parses.
5. Re-read the final live file with ruamel and assert the new value; only then
   report success.

## Ready-made harness

`scripts/surgical_scalar_edit.py` implements all of the above: backup, indent
detection, `width=4096` + `preserve_quotes`, diff-gate, text-surgical fallback,
and readback verification. Idempotent (reports `already target` when unchanged)
and restore-on-failure. One call per profile:

```bash
python surgical_scalar_edit.py --path /path/config.yaml \
    --key agent.max_turns --value 500 --label the operations agent
```

JSON line on stdout; exit 0 = ok (changed or already-target), 2 = missing,
3 = parse error, 4 = bad shape, 5 = backup exists, 6 = write/verify failed
(restored).
