# Transient "malformed inverted index" on a hot FTS5 database

Applies when `PRAGMA integrity_check` on a **live, heavily-written** database
reports `malformed inverted index for FTS5 table...` — and especially when a
human forwards it as "is it corrupted again?"

Distinct from `transient-torn-reads-on-live-db.md`, which covers whole-database
`malformed` from a torn snapshot read. This one is narrower and easier to
misread: base tables scan clean, only the FTS shadow indexes are named, and the
verdict is **not reproducible**.

## The measured case

A 2.95 GB Hermes `state.db` (480k messages, ~104k messages/day, previously
rebuilt after real corruption) reported:

```
=== quick_check ===
   ok

=== integrity_check(100000) -- FULL output ===
   malformed inverted index for FTS5 table main.messages_fts_trigram
   malformed inverted index for FTS5 table main.messages_fts
  (2 row(s))
```

Minutes later, the same file on the same host returned `ok`. Then eight
consecutive samples, three seconds apart:

```
sample 1..8: ok
distinct verdicts: ['ok']
STABLE
```

## Why it happens

`integrity_check` reads a WAL snapshot while the gateway is actively committing
FTS updates. On a database this hot, a check can land mid-commit and observe a
transiently inconsistent inverted index. It is a **measurement artifact on a
live database**, not damage on disk.

Note the shape: `quick_check` returned `ok` the whole time. That is the reverse
of the usual advice (`quick_check` is the weaker check and can miss real
damage), so do not use the two agreeing/disagreeing as your signal here.

## Procedure — do not answer from one sample

1. **Sample repeatedly before concluding anything.** One reading of a hot
   database is not a verdict. Eight samples with a short sleep is cheap and
   settles it. Report `STABLE` vs `INTERMITTENT` explicitly.
   `scripts/probe_fts_integrity_flap.py` does exactly this.
2. **Decide data loss from the BASE table, not the index.** FTS shadow tables
   are derived and rebuildable from `messages`; `messages` is not. Force-read
   every row rather than counting:

   ```python
   cur = con.execute("SELECT id, session_id, role, content FROM messages")
   while (rows:= cur.fetchmany(5000)):
       got += len(rows)
   ```

   `480,192 rows, 0 read errors` is the sentence that decides this. A bare
   `count(*)` does not — a corrupt B-tree reports phantom rows it cannot
   produce (see `offline-fts-rebuild-and-file-swap.md`).

3. **Exercise MATCH on EVERY FTS table.** Counting rows in a shadow table is not
   a test of the index.

   ```
   messages_fts MATCH ok hits=210919
   messages_fts_trigram MATCH ok hits=137411
   ```

   🔴 Filtering candidates with `name.endswith("_fts")` **silently skips
   `messages_fts_trigram`** — the trigram table was named in the original error
   and was the one never probed. Enumerate FTS tables explicitly.

4. **Run the control population.** Sweep every peer profile on every host. All
   13 other profiles returned `ok`, and the suspect later did too. A finding
   without a control is not a finding.

## Pitfalls

- **Answering from the first reading because it confirms a prior incident.**
  This database had genuinely been rebuilt days earlier, which makes "it is
  corrupt again" the comfortable conclusion. Sample first.
- **Reporting "false alarm" without explaining the mechanism.** The reading was
  real; the interpretation was wrong. Say which.
- **Inline `python3 -c` inside an `ssh` + shell `for` loop.** Nested quoting
  mangles the body into a `SyntaxError` that looks like a database result. Write
  the probe to a FILE, `scp` it, run it by path — the same rule that already
  applies to believing a `malformed` report.
- **Foreground timeouts swallowing the run.** `integrity_check(100000)` on a
  ~3 GB database takes minutes; eight samples exceeds a 180 s SSH budget. Start
  it detached, redirect to a file, then poll the file — and remember Python
  buffers stdout, so an empty output file does not mean the probe died. Check
  `pgrep -fc <script>` before assuming failure.
