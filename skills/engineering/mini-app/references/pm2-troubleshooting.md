# PM2 troubleshooting for mini-apps

Two distinct PM2 failure modes bite when operating mini-apps on a fleet machine.
Both present as "I restarted it but it's still serving old code."

## 1. The dual-PM2-daemon trap (most confusing)

There can be **more than one PM2 God Daemon running on the same machine**, each with
its own `PM2_HOME` and its own independent process table. A bare `pm2` command only
talks to the daemon selected by the current `PM2_HOME` (or the default `~/.pm2`).

Observed on the operator's Mac Studio:

- Mini-apps (sample-app, etc.) are supervised by the daemon at **`PM2_HOME=/Users/<user>/.pm2`**.
- A _separate_ Hermes-profile daemon runs at
  `/Users/<user>/.hermes/profiles/<agent-d>/home/.pm2`. Bare `pm2` in a <agent-d> shell
  frequently resolves to THIS one.

### Symptoms

- `pm2 restart <app>` → `Process or Namespace <app> not found`, OR it creates a NEW
  "errored" entry that never binds the port (restart count climbs: ↺ 15, ↺ 45...).
- Meanwhile the OLD process keeps serving stale code, because the _other_ daemon keeps
  respawning it. Killing the PID with `kill -9` does nothing durable — the owning
  daemon relaunches it within ~1s. You get into a kill/respawn race you cannot win
  from the wrong daemon.
- `pm2 list` shows the app as `errored`/`stopped` with `pid: 0` while `lsof -ti:<port>`
  still returns a live PID.

### Diagnosis

1. Find who actually owns the port and trace the parent:
   ```
   P=$(lsof -ti:3005 | head -1); PAR=$(ps -o ppid= -p $P | tr -d ' ')
   ps -o pid,command= -p $PAR        # reveals "PM2 ... God Daemon (/Users/<user>/.pm2)"
   ```
   The path in parentheses is the owning daemon's `PM2_HOME`.
2. List that daemon's processes explicitly:
   ```
   PM2_HOME=/Users/<user>/.pm2 pm2 jlist | python3 -c "import sys,json;[print(p['pm_id'],p['name'],p['pm2_env']['status'],'pid:',p['pid']) for p in json.load(sys.stdin)]"
   ```

### Fix

Always manage the app through the daemon that owns it:

```
PM2_HOME=/Users/<user>/.pm2 pm2 restart <app>
PM2_HOME=/Users/<user>/.pm2 pm2 save
```

Then delete any stray duplicate you accidentally created in the wrong daemon
(`pm2 delete <app>` in the default-home shell). Editing `server.js` requires a restart
under the CORRECT daemon to take effect — a restart on the wrong daemon is a no-op on
the live process.

Pitfall within the pitfall: do NOT sit in a `kill -9` loop trying to free the port.
The owning daemon respawns instantly. Stop/delete the entry in the owning daemon
FIRST, then the port frees and stays free.

## 2. The PM2 $HOME / os.homedir() trap (already known, recap)

A process launched under PM2 can see a rewritten `$HOME`, so `os.homedir()` inside the
app resolves to a profile home that may not contain the app's data files. Symptom: app
boots fine but every data panel is empty / `/healthz` reports "project files not
found." Fix: resolve data paths from an explicit list of absolute candidate paths at
startup instead of trusting `os.homedir()`. (The sample-app dashboard does this with
a `PROJECT_CANDIDATES` array.)

## Quick checklist when "my edit didn't take"

1. `lsof -ti:<port>` → get live PID. Is it even running?
2. Trace parent → which daemon owns it (`PM2_HOME`)?
3. Restart through THAT daemon's `PM2_HOME`.
4. Re-fetch a page and grep for a string you just changed to confirm the reload.
5. `PM2_HOME=<owning-home> pm2 save` so it survives reboot.
