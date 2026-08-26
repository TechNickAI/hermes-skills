# Verifying a durability mechanism, not just the service

A service can be perfectly healthy while its **durability** is dead. Health
checks, inference probes, and dashboards all pass because they exercise the
_live_ copy. Nothing exercises the backup path until you need it — by which
point the window of loss is however long nobody looked.

Worked case: the router's SQLite moved to a tmpfs RAM disk with a sync-to-disk
script. The service was healthy for two days. The sync had been failing the
entire time. A reboot would have lost everything since the migration.

## The rule

**When state lives on volatile storage, the persistence job needs its own
success check.** Treat "the service is up" and "the state survives a reboot" as
two independent claims requiring two independent proofs.

Symptoms that a durability path is dead while the service looks fine:

- persist/backup file mtime is hours or days behind the live file's mtime
- the sync script's own log line is absent from recent journal output
- the sync exits non-zero and nothing consumes the exit code

`stat -c '%y %s' <live> <persist>` is the ten-second version of this check. A
persist copy older than the last service restart means the mechanism is broken.

## Two failure modes found in one script

The sync used `cp` on a live WAL-mode SQLite file **and** the system `sqlite3`
CLI. Both are wrong, for different reasons:

1. **`cp` of a live WAL database produces a torn file.** It reads back as
   `database disk image is malformed` — see
   `references/sqlite-live-wal-false-corruption.md`. It silently writes a
   _plausible-looking_ 421 MB file that is not restorable.
2. **The distro CLI was older than the DB writer** (3.45.1 vs 3.53.3) and could
   not read the file at all, reporting real tables as `no such table`.

Fixed shape — online backup API, integrity-checked _before_ it replaces the
previous good copy:

```bash
TMP="${PERSIST}.tmp.$$"
trap 'rm -f "$TMP"' EXIT

node -e "
const D = require('$BS3');
const src = new D('$LIVE', { readonly: true });
src.backup('$TMP').then(() => {
  src.close();
  const v = new D('$TMP', { readonly: true });
  const ok = Object.values(v.prepare('pragma quick_check(1)').get())[0] === 'ok';
  const n = v.prepare('select count(*) c from <sentinel_table>').get().c;
  v.close();
  if (!ok) { console.error('quick_check failed'); process.exit(1); }
  console.log(' snapshot ok, rows=' + n);
}).catch(e => { console.error('backup failed: ' + e.message); process.exit(1); });
" || { echo "ERROR: snapshot failed; previous persist left intact" >&2; exit 1; }

mv -f "$TMP" "$PERSIST"
```

Three properties worth copying:

- **temp file + atomic rename** — a crash mid-write cannot corrupt the good copy
- **verify before promote** — a bad snapshot can never overwrite a good one
- **row count, not just `quick_check`** — an empty database passes every
  integrity check (see the false-corruption reference)

## Sizing volatile storage

tmpfs consumes RAM. Size it against the _write amplification_ of the engine, not
the current file size. A DB engine that rewrites the whole file on persist needs
~2× the DB size free; a WAL-mode native driver needs far less.

```bash
DBSZ=$(stat -c%s "$DB")
AVAIL=$(df --output=avail -k /mnt/<ramdisk> | tail -1)
[ $((DBSZ*2/1024)) -gt "$AVAIL" ] && echo "cannot absorb a full-file rewrite"
```

Resizing is in-place and non-destructive — data survives, no restart needed:

```bash
sudo sed -i 's/Options=size=1G,/Options=size=1.5G,/' /etc/systemd/system/<unit>.mount
sudo systemctl daemon-reload
sudo mount -o remount,size=1536M /mnt/<ramdisk>
df -h /mnt/<ramdisk>
```

⚠️ `mount -o remount,size=...,uid=...,gid=...,mode=...` on an existing tmpfs can
fail with `mount point not mounted or bad option` when the extra options are
replayed. Remount with **`size=` alone**; the existing uid/gid/mode persist.
Verify with `df -h` and confirm the files are still present afterwards.

## Report the exposure window explicitly

When a durability gap is found and closed, state the window in plain terms:
"there was no working backup from <date> until <time>; a reboot in that window
would have lost everything since." A user cannot weigh the risk of a near-miss
they were never told about, and the size of the window is the whole point.
