# PM2 dual-daemon targeting trap

## Symptom

You edit a mini-app's source (e.g. `server.js`), run `pm2 restart <app>`, and the
running site keeps serving the OLD code. Or `pm2 restart <app>` says
`Process or Namespace <app> not found`, or it creates a fresh entry that immediately
goes to `errored` / `restart-looping` and never binds the port — while a stale process
on the same port keeps answering requests.

## Root cause

There can be **two (or more) PM2 God Daemons running on the same machine**, each with
its own `PM2_HOME` and its own independent process list:

- The **default** daemon at `~/.pm2` (e.g. `/Users/nick/.pm2`).
- A **Hermes-profile** daemon at `~/.hermes/profiles/<profile>/home/.pm2`
  (this is the one bare `pm2` commands hit when the profile env is active, because
  `$HOME`/`PM2_HOME` is rewritten for the profile).

A mini-app launched under one daemon is invisible to the other. Bare `pm2` commands
go to whichever daemon your current `PM2_HOME`/`$HOME` resolves to, which is often NOT
the daemon that actually owns the running mini-app. So your restart hits the wrong
daemon (no-op or duplicate errored entry) while the real process — owned by the other
daemon — keeps running stale code and holding the port.

## Diagnosis

1. Find who actually owns the port:
   ```bash
   lsof -ti:<port>            # get the live PID
   ps -o ppid= -p <PID>       # get its parent
   ps -o command= -p <PPID>   # parent will be "PM2 vX: God Daemon (/path/.pm2)"
   ```
   The path in `God Daemon (<path>)` is the `PM2_HOME` that owns the process.
2. List each daemon's processes explicitly:
   ```bash
   PM2_HOME=/Users/nick/.pm2 pm2 jlist        # default daemon
   pm2 jlist                                  # whatever the current env points at
   ```

## Fix

Always manage the app through the daemon that owns it, by setting `PM2_HOME` explicitly:

```bash
PM2_HOME=/Users/nick/.pm2 pm2 restart <app>
PM2_HOME=/Users/nick/.pm2 pm2 save
```

Editing source requires a restart **under the correct daemon** to take effect.

## Pitfalls within the fix

- Do NOT `kill -9` the stale PID and `pm2 start` in a loop: if a daemon still has the
  app registered, it instantly respawns the process and you race yourself forever.
  Stop/delete the entry in the owning daemon first, then clear the port, then start once.
- A duplicate entry you accidentally created in the WRONG daemon will sit there
  `errored` and never bind (port already held by the real process). Delete it:
  `pm2 delete <app>` (in the wrong daemon) to clean up.
- After fixing, `PM2_HOME=<owner> pm2 save` so the correct daemon persists the state
  across reboots.

## Verify the edit actually landed

Restarting the wrong daemon "succeeds" but serves stale code. Confirm the new content
is live by fetching the rendered page and grepping for a string you just added/removed,
not by trusting the `pm2 restart... ✓` message.
