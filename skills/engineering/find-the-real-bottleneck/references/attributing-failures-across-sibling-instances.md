# Attributing a failure to the right process (multi-agent / multi-bot hosts)

Verified 2026-08-07. Class: you are diagnosing "component X is broken" on a host
or channel where **several near-identical instances of X are running**, and the
error you are reading may not belong to the instance you are investigating.

## The trap

A user reported a Telegram voice-memo download failure attributed to agent A.
Agent A's config was fixed and its gateway restarted at `14:26:09`. The user then
sent another voice memo and it failed again — so the natural read was "my fix
didn't work, re-diagnose A."

Both assumptions were wrong:

1. **The new failure belonged to a different agent.** The user had _replied_ to
   agent B's message, and reply-anchoring routed the media to B's gateway, which
   still carried the unpatched default. A's gateway had logged nothing since the
   restart.
2. **The failures that looked post-fix were pre-fix.** The two events read out of
   A's log were timestamped `14:22` and `14:25` — both _before_ the `14:26:09`
   restart. Tailing a log and seeing the failure string says nothing about
   whether it postdates your change.

Net effect: a correct fix was nearly reverted, and a second exposed instance went
unnoticed for several more minutes.

## Three checks before concluding "my fix didn't work"

Run all three. Each is one command.

**1. Which instance logged it?** Grep the failure signature across _every_
sibling instance's log, not just the suspect's.

```bash
for p in <all profiles/instances>; do
  n=$(grep -c "<failure string>" <root>/$p/logs/<log> 2>/dev/null || echo 0)
  printf "  %-10s %s\n" "$p" "$n"
done
```

**2. Is the event actually after your change?** Filter by restart timestamp
rather than eyeballing a tail. With ISO-ish log prefixes, string comparison works:

```bash
awk '$0 >= "2026-08-07 14:26:09"' gateway.log | grep "<failure string>" \
  || echo "  (none after restart)"
```

Also pin the restart instant independently — do not trust memory:
`ps -p <pid> -o lstart=` and `launchctl print user/501/<label> | grep "pid = "`.

**3. Who was the user actually addressing?** In multi-bot rooms the inbound log
line carries `reply_to_id` and `reply_to_text`. That identifies the addressee and
therefore which gateway received the payload.

## Corollary: a shipped default has fleet-wide blast radius

Once the cause turned out to be a **library/framework default** rather than a
member-specific misconfiguration, every instance was exposed by construction —
including the diagnosing agent's own. Two consequences:

- **Fix your own instance too.** The diagnostician is not outside the population.
- **Zero failures elsewhere is not immunity.** The other profiles showed 0
  occurrences only because they receive almost no traffic of that kind. Absence
  of traffic is not absence of exposure — say that explicitly rather than
  reporting "4 of 5 profiles unaffected."

## Reporting

When you discover the misattribution, correct it in the first line rather than
burying it: _"I need to correct my last message. The failure was mine, not X's."_
Then state precisely what the mistake changes about the diagnosis, and what is
still unproven. the operator tracks claims across turns and will find the contradiction
before you surface it.
