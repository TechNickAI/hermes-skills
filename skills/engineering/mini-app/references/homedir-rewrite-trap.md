# The `os.homedir()` rewrite trap in mini-apps

## Symptom
A mini-app dashboard running under PM2 loads and returns a 200, but every data panel shows 0 entries. `/healthz` returns "project files not found". `state.json` has empty arrays.

## Root cause
Hermes rewrites `$HOME` and `~` for its tool environment to the current profile's home (e.g. `/Users/nick/.hermes/profiles/<agent-d>/home/`). A Node.js process started by PM2 *while inside a Hermes tool call* inherits this rewritten `HOME`. At runtime, `os.homedir()` returns the profile home, not `/Users/nick`. Any path built with `path.join(os.homedir(), '.openclaw/...')` silently does not exist.

The app keeps running, loads fine in the browser, but reads zero bytes from its source-of-truth files.

## Diagnosis checklist
1. `curl -s http://localhost:<port>/healthz` → "project files not found" confirms the bug.
2. `ps eww <pid> | tr ' ' '\n' | grep HOME=` → shows the rewritten HOME.
3. Direct node test: `node -e "const os=require('os'); console.log(os.homedir())"` under the PM2 shell shows the wrong path.

## Fix
Never derive data-source paths from `os.homedir()` at runtime. Instead:

```js
// server.js — priority chain: explicit env var > hardcoded absolute path
const PROJECT_DIR = process.env.BTC_PROJECT_DIR ||
  '/Users/nick/.openclaw/workspace-<agent-d>/memory/projects/btc-recovery-changetip';
```

Or set in `ecosystem.config.js`:
```js
env: {
  BTC_PROJECT_DIR: '/Users/nick/.openclaw/workspace-<agent-d>/memory/projects/btc-recovery-changetip',
}
```

After fixing, `pm2 delete <name>` + `pm2 start ecosystem.config.js --only <name>` to reload with new env.

## Applies to
Any mini-app that reads from dotfiles or project directories using `os.homedir()`, `~`, or `$HOME` inside a Node or Python process launched from a Hermes tool session.
