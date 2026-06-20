---
name: collect-context
description: >-
  Use when collecting qualitative market context for the target stablecoin —
  latest news, the Fear & Greed index, and trending narratives — from the
  CoinMarketCap MCP server into a JSON cache. Post-recommend opt-in advisory
  enrichment (not a fast-path stage); feeds recommend's market-context block only,
  never safety_score, and never changes the ranking. Run it after the first ranking,
  then re-run recommend. Needs only a CMC API key in ~/.versusos/.env (or the
  CMC_PRO_API_KEY env var).
---

# VersusOS — Collect Market Context (CMC MCP)

Collect the qualitative context the numbers miss: coin-specific news, the
market-wide Fear & Greed index, and trending narratives. Every item comes
from the CoinMarketCap MCP server — the collector script speaks MCP
(JSON-RPC over HTTP) **directly**, so no MCP client registration is needed —
and carries its source URL so downstream annotations can cite it.

## Pipeline

Fast path (deterministic core): `collect → score → recommend` (where `collect` runs
`collect-vault → collect-dex`). `collect-context` is one of the **three post-recommend
opt-in enrichments** — run it
after the first ranking, then re-run `recommend` to fold in a market-context block.
It is **advisory: it never feeds `safety_score` and never changes the ranking** (the
score-affecting enrichment is `collect-depeg-history`; `research-audit` is the other
advisory one). The fast path proceeds without this cache and states "no market
context collected".

## When to use

- Running a VersusOS evaluation and the context cache is missing or stale.
- The user asks for news / sentiment / narrative context on a stablecoin.

Not for: numeric collection (collect-vault / collect-dex), scoring (score),
or ranking (recommend).

## Requirements

Python ≥3.10, standard library only — no install. A CoinMarketCap API key
(the same key collect-dex uses; free signup at
https://pro.coinmarketcap.com), provided once in the dotenv-style key file
**`~/.versusos/.env`**:

```
CMC_PRO_API_KEY=<your key>
```

The `CMC_PRO_API_KEY` env var also works and takes precedence. **Nothing
else** — no `claude mcp add`, no MCP server setup.

## Workflow

**Announce at start:** "VersusOS — collect-context (post-recommend advisory
enrichment): collecting market context via CMC MCP."

Run the collector from this skill folder:

```
python scripts/collect.py [--mapping ../collect-vault/data/defillama_yields.json] [--config config/collect.json] [--out data/context.json] [--extra-symbols ETH,BTC] [--all-symbols]
```

It reads the target coin symbols from the collect-vault cache
(`vaults[].symbol`), splitting LP-pair symbols on `-` (e.g. `"USDC-USDT"` →
`USDC`, `USDT`), de-duplicating in first-seen order, and **filtering to the
`stablecoin_whitelist`** in `config/collect.json` (case-insensitive) so pair
vaults' non-stable partners (WETH, ZEC, …) and protocol-wrapped vault-token
noise are dropped. It then resolves each symbol to its CMC id, fetches per-coin
news plus one Fear & Greed and one trending-narratives call, and writes the
cache. A run is a few seconds. Then present the result as described under
Presenting results.

**Scope overrides** (the whitelist is the default scope; widen it on request):
- `--extra-symbols A,B` — research these coins **in addition** to the
  whitelist, even if absent from the vault set (e.g. the user asks for ETH news).
- `--all-symbols` — bypass the whitelist and research **every** vault symbol
  (slow / credit-heavy; includes non-stablecoins).

## Data cache

| Data | Path | Produced by |
|------|------|-------------|
| Market context (news, Fear & Greed, narratives) | `data/context.json` | `python scripts/collect.py` |

**Freshness:** fresh while `fetched_at` (UTC) is within **60 minutes** (the
pipeline-wide rule). Older or missing means stale.

## Output schema

```json
{
  "source": "coinmarketcap-mcp",
  "fetched_at": "<UTC ISO-8601>",
  "fear_greed": { "value": 15, "classification": "Extreme fear" },
  "stablecoins": [
    {
      "symbol": "USDC",
      "news": [
        { "title": "…", "date": "11 June 2026 12:43 AM UTC+0", "url": "https://…" }
      ]
    }
  ],
  "narratives": [ { "rank": 1, "name": "…", "url": "https://…" } ]
}
```

- Every news item carries its URL — items without one are dropped by the
  collector, never invented.
- `fear_greed.value` is the 0–100 index; `classification` is CMC's label.
- A coin that failed or did not resolve still appears with empty `news`.

## On failure

- **No API key found** → the script exits with a clear error before any
  network call. Create `~/.versusos/.env` as a template (the single line
  `CMC_PRO_API_KEY=` with an empty value, directory created, permissions
  `600`), tell the user to open the file and fill in their key, then stop
  and wait. Never ask the user to paste the key into the chat; never echo a
  key.
- One tool or coin failing → warned on stderr, the rest is kept, and the
  cache is still written (partial context beats none) — `fear_greed` may be
  `null` and lists empty.
- Nothing collected at all → exit non-zero, existing cache preserved.
- Downstream stages never block on this skill; never fabricate news items,
  index values, or narratives.

## Presenting results

1. A summary line: news counts per coin, the Fear & Greed value, narrative
   count, and `fetched_at`.
2. The headlines with dates (newest first).
3. **Next stage** — re-run `recommend` to fold the market-context block into the
   recommendation. (Context is advisory — it annotates only; it never re-scores
   or re-ranks.)

Always state these items are qualitative context only — they never change the
deterministic scores or the ranking; `recommend` surfaces them as a cited
market-context block.

## References

- `./references/data-sources.md` — the CMC MCP endpoint, protocol notes,
  tools, and response shapes.
- `./config/collect.json` — options: news limit, throttle, and the
  `stablecoin_whitelist` (default collection scope; override with
  `--extra-symbols` / `--all-symbols`).
