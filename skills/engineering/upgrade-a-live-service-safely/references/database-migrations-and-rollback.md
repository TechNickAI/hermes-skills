# Migrations are the one-way door, not the code

The single most important correction from the 2026-07-28 the router v3.8.49
deploy. I had told the user **"rollback is just flipping the symlink back."**
That was wrong, and would have produced a broken rollback under pressure.

## Why a symlink flip is NOT a rollback

Blue/green with a release-dir + symlink makes the **code** swap atomic. It does
nothing for the **database**. If the new build applies schema migrations on
first boot, the moment it serves one request you have:

```
old code  +  new schema  =  not the state you rolled back to
```

Measured case: v3.8.49 applied **11 pending migrations (123→133)** on first boot
against a DB sitting at 122. Two were destructive:

| migration                           | destructive statements                                      |
| ----------------------------------- | ----------------------------------------------------------- |
| `126_reasoning_routing_rules`       | 3                                                           |
| `130_remove_unregistered_qwen_data` | `DELETE FROM provider_connections`, `DELETE FROM key_value` |

## The rule

**Before ANY cutover that may migrate, snapshot the data store, and make
rollback restore code AND data together.**

```bash
# immediately before the symlink flip
mkdir -p "$BACKUP_DIR"
SNAP="$BACKUP_DIR/storage-pre-$SHA-$(date +%Y%m%d%H%M%S).sqlite"
sqlite3 "$DB" ".backup '$SNAP'" 2>/dev/null || cp "$DB" "$SNAP"
echo "$SNAP" > "$APP_DIR/.previous_db_snapshot"
readlink -f "$CURRENT" | xargs basename > "$APP_DIR/.previous_release"
```

Rollback then restores both, in this order: **stop → restore DB → flip symlink
→ start → verify**.

Use the engine's own backup API (`sqlite3 .backup`, `pg_dump`) rather than `cp`
where possible — `cp` on a live WAL-mode SQLite file can capture a torn state.
Keep the `cp` fallback so a missing binary can't block the deploy.

## Rehearse the migration before it touches production

The staging instance must run against a **copy** of the live DB, not an empty
one. That's what actually exercises all pending migrations:

```
cp "$DB" "$TESTDATA/storage.sqlite"
# start release on the ALT port with DATA_DIR=$TESTDATA
```

If migrations are going to fail or destroy something unexpected, they do it on
the throwaway copy while production keeps serving.

## Enumerate what will run, before you run it

Never let migrations be a surprise. Diff applied-vs-shipped and grep for
destructive statements:

```bash
# what's applied now
sqlite3 "$DB" "SELECT MAX(CAST(version AS INTEGER)) FROM _omniroute_migrations;"

# what the new release ships, beyond that point
ls "$REL/.build/next/standalone/migrations/" | sort -V | awk -F_ '$1+0 > 122'

# which of those are destructive
grep -icE "drop table|drop column|delete from|truncate" "$M/<file>.sql"
```

Report the destructive ones to the user **before** cutover. This is the
difference between an informed go-ahead and a surprise.

## Verify the destructive ones were survivable, after

```
provider_connections: 14 rows   ✅ intact
api_keys: 12                    ✅ intact
breakers: all CLOSED            ✅
```

A migration named `remove_unregistered_*` may well be correct and harmless —
but confirm it with a row count rather than assuming.

## Outcome when done right

```
[19:27:01] live PID=3060  migrations=122
[19:27:01] DB   -> storage-pre-6c26483d4-...sqlite (309M)
[19:27:16] PID 3060 -> 53438
[19:27:25] === DEPLOY VERIFIED ===  migrations now: 133
```

~15s downtime, 8/8 verification gates green, full restore path available.
