# <agent-a> MEMORY.md cleanup — 2026-06-05

## Scope

Planned reduction: 6,101 bytes → ~1,700 bytes (~72%).
Achieved: 6,101 → 2,048 bytes (66.4%).

## Backup

`MEMORY.md.bak-20260605-134836` — 6,101 bytes.

## Entry inventory and verdicts

| Entry (summary)                                     | Size (chars) | Action                                           | Skill target                                                      | Target already had detail?              |
| --------------------------------------------------- | ------------ | ------------------------------------------------ | ----------------------------------------------------------------- | --------------------------------------- |
| How Memory Works (7 §-entries)                      | ~771         | COMPRESSED to 1 entry                            | —                                                                 | —                                       |
| Bot↔bot firebreak                                  | ~280         | **KEPT VERBATIM** (protected)                    | —                                                                 | —                                       |
| Hermes-agent PR routing + repo names                | ~259         | COMPRESSED                                       | —                                                                 | —                                       |
| Router keys / omniroute / 9router                   | ~449         | COMPRESSED                                       | —                                                                 | —                                       |
| Fleet skills authorship (Nick)                      | ~227         | COMPRESSED                                       | —                                                                 | —                                       |
| config.yaml ruamel pitfall                          | ~501         | REPLACED with pointer                            | `fleet-management/references/config-editing.md`                   | ✅ Yes                                  |
| OpenClaw→Hermes migration how-to                    | ~820         | REPLACED with pointer                            | `devops/skill-migration-audit/SKILL.md`                           | ✅ Yes                                  |
| Fleet audit log (per-member sources)                | ~877         | DELETED                                          | `skill-migration-audit/references/fleet-member-sources.md`        | ✅ Yes                                  |
| $HOME shim full mechanics                           | ~925         | REPLACED with pointer                            | `openclaw-imports/<agent-a>-profile-home-shim/SKILL.md`           | ✅ Yes                                  |
| report skill deployment log (PR #32, rollout steps) | ~599         | DELETED (stale log); config fact KEPT compressed | `report/SKILL.md`                                                 | ✅ Yes — BUG_BOARD_OWNER, routing logic |
| Model-config drift audit                            | ~270         | REPLACED with pointer                            | `fleet-management/references/local-profile-model-config-audit.md` | ✅ Yes                                  |
| /recall placement (appended mid-run)                | ~175         | COMPRESSED to 1 line                             | `recall/`, `recall-from-openclaw/` skills exist                   | ✅ Yes                                  |

## Deviations from plan

- **None for planned entries.** All six skill targets already contained the required detail — no append-first step needed.
- **One unplanned entry:** The memory system appended a `/recall` placement note between backup and first write. Compressed rather than deleted (durable fact).
- **Size gap (66.4% vs 72%):** The untouchable firebreak entry (~280 bytes) + compressed `/recall` entry (~116 bytes) account for ~396 bytes above the 1,700-byte target. No further cuts possible without removing protected or durable content.

## Final file (22 lines, 2,048 bytes)

12 entries after compression:

1. Preamble (how memory works, security)
2. Bot↔bot firebreak (verbatim)
3. `---` separator
4. Hermes-agent PR routing
5. Router keys / omniroute
6. Fleet skills authorship
7. Config edits → fleet-management reference
8. Migration skill pointer
9. $HOME shim pointer
10. report skill config facts
11. Model-config drift pointer
12. /recall placement

## Verification run (Python)

```
before: 6101  after: 2048  saved: 4053  reduction: 66.4%
firebreak intact: True
firebreak unchanged: True (byte-identical entry)
entries_before: 18  entries_after: 12
```
