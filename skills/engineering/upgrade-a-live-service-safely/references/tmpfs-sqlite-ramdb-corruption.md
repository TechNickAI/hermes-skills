# tmpfs RAM-disk SQLite: naive `cp` persist corrupts the durable twin

Worked case on the (ubuntu@<router-host>).

## Symptom

User hits "disk io error" in the dashboard when testing a provider connection
right after the service restarted. The router keeps serving traffic.

## Layout that caused it

The SQLite store was moved to a tmpfs RAM disk (Aug 11) for I/O:

```text
/mnt/the router-ramdb/            tmpfs mount (systemd mnt-the router\x2dramdb.mount)
  Options=size=1G,uid=1000,gid=1000,mode=0700
  storage.sqlite                 LIVE DB
  storage.sqlite-wal / -shm      sidecars
/home/ubuntu/.the router/storage.sqlite        -> symlink to the RAM file
/home/ubuntu/.the router/storage.sqlite.persist  durable twin on EBS
```

Durability scripts:

- `the router-ramdb-restore.sh` — ExecStartPre: copies `.persist` into RAM if the
  RAM copy is missing (post-reboot).
- `the router-ramdb-sync.sh` — periodic/ExecStopPost: `cp "$LIVE" "$TMP"; mv -Tf` —
  **the bug**: copies the LIVE WAL-mode DB with plain `cp`.

## Journal evidence (restart sequence)

```text
Aug 13 14:14:47 node[534890]: [Shutdown] SQLite database checkpointed and closed.
Aug 13 14:14:48 the router-ramdb-sync.sh[553678]: synced... -> storage.sqlite.persist (421539840 bytes)
Aug 13 14:14:48 Started the router.service...
Aug 13 14:14:49 node[553694]: [DB]... Cannot find module 'better-sqlite3' (harmless driver probe noise)
Aug 13 14:14:50 node[553694]: [DB] SQLite database ready
```

Clean shutdown checkpointed, THEN the sync `cp`'d the live file. The copy was
torn (the sync ran against a checkpointed-consistent file here, but a copy of a
WAL-mode DB taken while the app writes — exactly what a periodic sync does — is
not guaranteed consistent). Result: `.persist` reads back
`database disk image is malformed` while the RAM DB reads clean.

## Verification that discriminated real vs false corruption

```python
for label, path in (("RAM", "/mnt/the router-ramdb/storage.sqlite"),
                    ("PERSIST", "/home/ubuntu/.the router/storage.sqlite.persist")):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True); c.execute("pragma query_only=on")
    print(label, c.execute("select count(*) from combos").fetchone()[0],
                c.execute("select count(*) from provider_connections").fetchone()[0])
# RAM:     ok, tables read
# PERSIST: DatabaseError: database disk image is malformed
```

Also check the mount itself (the "RAM is full → disk I/O error" variant):

```bash
df -h /mnt/the router-ramdb; free -h          # tmpfs capacity + RAM headroom
mount | grep ramdb                            # Options=size=... (1G here, DB 421MB & growing)
```

## Rules

1. **Never `cp` a live WAL-mode SQLite file for backup/persist.** Use
   `sqlite3.backup <file>` (online backup API, consistent even mid-traffic) or
   checkpoint first, then copy. Verify the copy reads clean afterwards.
2. **Size tmpfs with headroom.** When the DB outgrows the mount, SQLite fails
   writes with exactly `disk I/O error` — indistinguishable from hardware without
   checking the mount. The DB grows with usage; 1G for a 420MB-and-growing DB is
   a near-term wall.
3. **`.persist` is the durability promise.** On ungraceful reboot the RAM copy is
   gone; the app restores from `.persist`. A corrupt persist twin silently
   converts a routine restart into data loss. Treat it as a first-class backup
   and verify it in the same cadence as the RAM copy.
4. **RAM disk + a clean-shutdown sync is still a crash window.** Anything between
   the last periodic sync and a hard power cut is lost. If that's acceptable,
   fine — just say it out loud rather than believing `.persist` is a full mirror.

## Repair direction (proposed, not yet applied at time of writing)

Reconcile `.persist` from the intact RAM DB using `sqlite3.backup`, verify both
read clean, then fix `the router-ramdb-sync.sh` to use `sqlite3.backup` instead
of `cp`. Reversible, no live data at risk (RAM copy is the source of truth).
