# Locating a live web app's source before editing it

**Trigger:** User sends a screenshot or a URL and says "fix X on the dashboard /
the app / this page." Before touching any code, confirm WHICH app it is and WHERE
its source lives. A user can operate several dashboards across different platforms;
the one in the screenshot is frequently NOT the one you've been editing.

## The trap (real example)

Asked to "fix the column labels" on a screenshot showing `mentionsterminal.com/n`
with a "Word Matrix" / "Live Market Comparison" card. The assumption was that this
was the on-box `hangl-dashboard` (the internal Kalshi dashboard behind the Caddy
auth gate). It was not. mentionsterminal.com is a **separate, externally hosted
app** whose source is not on the box and not in the user's GitHub orgs. Editing
hangl-dashboard would have "fixed" the wrong app.

## Trace procedure (do this BEFORE writing code)

1. **Grep the box for the app's unique strings** — pull distinctive UI copy from the
   screenshot (card titles, placeholders, headings) and search source trees:

   ```bash
   grep -rl --exclude-dir=node_modules --exclude-dir=.git \
     -i "Word Matrix\|Live Market Comparison\|Paste Kalshi NFL" /home/ubuntu/src /home/ubuntu/apps
   ```

   No hits = the code isn't on this machine.

2. **Check what's actually running** vs. the domain in the screenshot:

   ```bash
   pm2 list # what processes serve apps here
   grep -i "<domain-or-slug>" ~/mini-apps/router/Caddyfile # is it even routed here?
   ```

   If the domain isn't in the Caddyfile and no PM2 process matches, it's hosted
   elsewhere.

3. **Check GitHub** (user's orgs) for a matching repo:

   ```bash
   gh repo list <org> --limit 200 | awk '{print $1}'
   gh search code "<unique UI string>"
   ```

4. **Fingerprint the live site** — curl the HTML and read its metadata:
   ```bash
   curl -sI https://<domain>/ # server header (cloudflare/vercel/render), x-deployment-id
   curl -s https://<domain>/ | grep -iE "<title>|og:image|generator|/_next/|build|commit"
   ```

## Platform fingerprints

- **Lovable.app** (no-code / vibe-coding platform): `og:image` points at a
  `*.lovable.app` preview URL, and the HTML carries a Lovable commit-SHA script tag
  (`data-commit-sha=...`, `/__l5e/events.js`, `/~flock.js`). Source lives inside the
  Lovable project, NOT in a GitHub repo (unless the user explicitly connected one).
  You cannot edit it from the box — either the user pastes a change prompt into
  Lovable, connects the project to GitHub, or you drive it in the browser with login.
- **Vercel:** `x-vercel-id` / `server: Vercel` header; `/_next/static/...` assets.
- **Render:** `x-render-*` headers; `render` CLI (`render services`) needs interactive
  login, so it won't list services non-interactively.
- **On-box (this fleet):** routed in `~/mini-apps/router/Caddyfile`, served by a PM2
  process, behind the auth sidecar. THIS is the only class you can edit + deploy
  directly. See the main SKILL.md.

## When the source isn't reachable

Don't fake a fix. Hand the user a ready-to-paste change description (for Lovable,
write it as a plain-English prompt: what to change, the exact CSS/behavior, what NOT
to touch) and offer the real paths: connect the repo to GitHub, or drive the browser
with login. State plainly that the app isn't on the box so you can't edit a file
directly — that's honesty, not a refusal.
