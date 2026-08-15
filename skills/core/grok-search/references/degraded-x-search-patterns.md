# Degraded X/Twitter Search Patterns

When `grok_search.py` fails (missing `XAI_API_KEY`, network error, etc.) and the user's
research goal requires X/Twitter-native sources, these `web_search` patterns recover
useful secondhand coverage.

## Core technique: `site:x.com` scoping

```
web_search("site:x.com <topic> <year> <specific terms>", limit=10)
```

This returns indexed X post snippets from Google/Bing. Snippets are short (title +
~150 char description) but often contain the key claim with an `x.com/...` URL.

## Proven patterns from session (Solana copy-trading, July 2026)

### Practitioner PnL claims

```
site:x.com "copy trading" "win rate" OR "PnL" OR "profitable" Solana <year>
site:x.com "same block" OR "same slot" copy trade bot latency
site:x.com <specific-wallet-or-KOL-name> Solana copy trading
```

### Infrastructure claims

```
site:x.com Helius OR Yellowstone OR Jito OR ShredStream "copy trade" latency
site:x.com "milliseconds" OR "100ms" OR "sub-second" Solana bot
```

### Consensus/cluster signals

```
site:x.com "multiple wallets" "same token" Solana signal buy
site:x.com "3+ wallets" OR "consensus" KOL Solana
```

### Failure modes

```
site:x.com copy trading "exit liquidity" OR "sandwich" OR "unprofitable" Solana
site:x.com "leader sells" OR "front-run" copy trade bot
```

## Extracting from aggregator posts

X URLs returned by `site:x.com` search usually fail in `web_extract` (auth walls, JS
rendering). Instead, extract from the **aggregator pages** that cite or embed the X posts:

- Blog posts that embed X quotes (Medium, dev.to, CoinTelegraph, Decrypt)
- Dune dashboard pages that the X posts link to
- GitHub repos mentioned in X threads
- News aggregator pages (CoinStats, Blockchain.news)

These secondary sources often quote the X content verbatim or reproduce key numbers.

## Limitations

- Snippets are truncated — you see titles and ~150 chars, not full threads
- No thread context (replies, quote-tweets that add nuance)
- Date filtering is approximate (search engines lag real-time by hours/days)
- Marketing-heavy topics (copy trading bots, trading tools) are dominated by paid content
  farms that embed X posts — always flag `[PAID-PRODUCT AD]` on vendor sources
- Cannot distinguish organic vs astroturfed X posts from snippets alone
