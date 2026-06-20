---
name: collect-dex
description: >-
  Use when collecting each stablecoin vault token's DEX pool data — discovering
  every USDC/USDT-paired pool (liquidity, pooled amounts per side, price) and
  persisting those that can affect the safety score — seeded from the
  collect-vault cache. Discovery via Dexscreener token-pairs; snapshots via the
  CoinMarketCap v4 DEX API (primary). Emits gecko_network and history_selected
  per pool for the collect-depeg-history skill. Feeds the liquidity factors of
  the safety score.
---

# VersusOS — Collect Designated-DEX Data (CMC)

Collect, for each stablecoin vault token's **discovered DEX pools**, the data
VersusOS needs to judge the coin itself: pool liquidity, how much of each token
sits in the pool, and the pool's own current price. Pools are **discovered**
per vault token (seeded from the collect-vault cache's `underlyingTokens`) via
Dexscreener `token-pairs/v1`, filtered to pools whose counterparty side is USDC
or USDT (by on-chain address). **Snapshots** come from the **CoinMarketCap v4
DEX API** (primary source; falls back to Dexscreener when CMC does not index
the pool). Per-side pooled amounts always come from Dexscreener. This skill
collects **snapshots only** — OHLCV history is handled by the opt-in
`collect-depeg-history` skill. Each pool record carries `gecko_network` and
`flags.history_selected` so that skill knows which pool to deep-collect.
Only pools that can move the score are persisted: a pool is written when its
snapshot liquidity clears the Pool Liquidity floor (config `min_pool_liquidity`,
$50K) or it is the per-target history pool; the rest feed no factor and are
dropped (counted under `dropped_unscored`). All peg and liquidity judgments come
from these pools — never from an aggregate or cross-venue feed.

## Pipeline

Fast path (deterministic core): `collect → score → recommend`, where `collect` (the
fast-path collection orchestrator) runs `collect-vault → collect-dex` — **this skill
is collect's step 2**, seeded by collect-vault's fresh cache. After the first
recommendation, three opt-in enrichments deepen the analysis (recommend orchestrates
them): `collect-depeg-history` re-runs score for a 0–200 deep, **re-ranked** result
(**score-affecting**); `research-audit` and `collect-context` add audit and
market-context annotations (**advisory — ranking unchanged**). For an end-to-end
evaluation, the recommend skill orchestrates every stage.

## When to use

- Starting a VersusOS evaluation and the DEX cache is missing or stale (see the
  freshness rule under Data cache).
- The user asks to refresh DEX pool / peg / liquidity data for a stablecoin.

Not for: vault APY/TVL collection (use collect-vault), qualitative context
(collect-context), scoring (score), or ranking (recommend).

## Requirements

Python ≥3.10, standard library only — no install. A CoinMarketCap API key
(free signup at https://pro.coinmarketcap.com; quotes cost 1 credit per
pair), provided once in the dotenv-style key file **`~/.versusos/.env`**:

```
CMC_PRO_API_KEY=<your key>
```

The `CMC_PRO_API_KEY` env var also works and takes precedence (CI / power
users). The collector exits with a clear error before any network call if
neither is present. The discovery source (Dexscreener) needs no key.
**collect-vault must have run first** — its cache
(`skills/collect-vault/data/defillama_yields.json`) is the discovery seed.

## Workflow

**Announce at start.** *Orchestrated (by collect/recommend):* stay **silent** — no
announce, no stage handoff. *Standalone:* one short product-friendly line, no
skill/stage names — e.g. "Collecting market & liquidity data…"

Run the collector from this skill folder:

```
python scripts/collect.py [--vaults ../collect-vault/data/defillama_yields.json] [--config config/collect.json] [--out data/dex_pools.json]
```

The pipeline:
1. Reads `underlyingTokens` from the collect-vault cache to seed target tokens
   (one seed per distinct `(chain, token_address)`, Solana/unsupported chains
   skipped).
2. Calls Dexscreener `token-pairs/v1` per seed to discover every pool
   containing the token; keeps only pools whose counterparty address is in
   `counterparty_whitelist` (config).
3. Batches CMC `quotes/latest` for chains CMC serves (the `cmc_networks`
   allowlist — bsc/avalanche are unsupported and skip straight to fallback).
   Addresses are filtered to plain contract addresses (CMC 400s on pool-id
   hashes and Curve composites) and chunked `cmc_batch_size` per call (avoids
   HTTP 414 on big chains); falls back to the Dexscreener pair snapshot for
   pools CMC does not index or cannot query.
4. Selects the single most-liquid price-sane pool per target **whose address is a
   plain contract address** (GeckoTerminal 404s on Uniswap-v4 pool ids / Curve
   composites) and marks it `flags.history_selected = true`; records
   `gecko_network` for each pool so `collect-depeg-history` can fetch OHLCV later.
5. Persists only the pools that can affect the score: those with snapshot
   liquidity ≥ `min_pool_liquidity` (config, $50K — the Pool Liquidity floor)
   plus every `history_selected` pool. Pools below the floor that are not a
   history pool contribute to no factor, so they are dropped from the cache
   (reported as `dropped_unscored`).

Then present the result as described under Presenting results.

## Data sources per field

| Field(s) | Source | Notes |
|---|---|---|
| Discovery (which pools exist) | Dexscreener `token-pairs/v1` | Per-token; bare-array response; no key; filtered to whitelisted counterparty addresses |
| `price_usd`, `price_in_counterparty`, `liquidity_usd`, `volume_h24`, `raw` | CMC v4 DEX `quotes/latest` (primary) | 1 credit per pair; `snapshot.source = "cmc"` |
| All snapshot fields (fallback) | Dexscreener pair from discovery | Used when CMC does not index the pool; `snapshot.source = "dexscreener"` |
| `pooled_target`, `pooled_counterparty` | Dexscreener `liquidity.base`/`liquidity.quote` | Always from Dexscreener — CMC does not serve per-side amounts |
| `gecko_network` | `gecko_aliases` config | GeckoTerminal network id per pool; consumed by `collect-depeg-history` |
| `flags.history_selected` | `discovery.history_targets` | `true` for the top-1 most-liquid price-sane **plain-contract-address** pool per target (GeckoTerminal-fetchable); `collect-depeg-history` fetches OHLCV only for these |

**CMC discovery infeasibility (live-verified 2026-06-16):** `spot-pairs/latest`
cannot discover pools by token — it requires a known dex slug; the
`base_asset_*`/`quote_asset_*`/`liquidity_min`/`sort` filters are silently
ignored and it returns no per-side pooled amounts. Discovery therefore stays
on Dexscreener; CMC `quotes/latest` remains the snapshot source for the
discovered pool addresses.

## Data cache

Output is written relative to this skill folder and read by later pipeline
stages (never re-fetched by them). If a later stage finds it missing, run the
collector first, then retry.

| Data | Path | Produced by |
|------|------|-------------|
| Discovered DEX pool snapshots | `data/dex_pools.json` | `python scripts/collect.py` |

**Freshness:** the cache is fresh while its `fetched_at` (UTC) is within
**60 minutes**; older or missing means stale — re-run the collector before
relying on it. If the user explicitly asks to use an older cache, do so, but
state its age.

## Output schema

The cache file is the contract downstream skills read:

```json
{
  "source": "coinmarketcap-dex+dexscreener",
  "fetched_at": "<UTC ISO-8601>",
  "history_window_days": 180,
  "counts": {
    "target_tokens": <int>,
    "qualifying_pools": <int>,
    "snapshot_ok": <int>,
    "persisted_pools": <int>,
    "dropped_unscored": <int>
  },
  "stablecoins": [
    {
      "symbol": "USDC",
      "pools": [
        {
          "chain": "ethereum", "dex": "uniswap-v3",
          "pool_address": "0x…", "token_address": "0x…",
          "gecko_network": "eth",
          "snapshot": {
            "price_usd": 1.00049,
            "price_in_counterparty": 1.0004972,
            "liquidity_usd": 19735677.8,
            "pooled_target": 3008666,
            "pooled_counterparty": 16725515,
            "counterparty": { "symbol": "USDT", "address": "0x…" },
            "volume_h24": 12623670.66,
            "source": "cmc",
            "raw": { "…full CMC pair object (holders, security_scan, taxes)…" }
          },
          "flags": {
            "history_selected": true
          }
        }
      ]
    }
  ]
}
```

- `counts.target_tokens` is the number of distinct `(chain, token_address)`
  seeds; `counts.qualifying_pools` is the total discovered pools across all
  targets after whitelist filtering; `counts.snapshot_ok` is how many of those
  got a snapshot. `counts.persisted_pools` is how many were written (cleared the
  liquidity floor or are a history pool) and `counts.dropped_unscored` how many
  were discarded as score-irrelevant (`qualifying_pools = persisted_pools +
  dropped_unscored`).
- All snapshot fields are oriented to the **target** stablecoin
  (`token_address`): `pooled_target` is its in-pool amount,
  `pooled_counterparty` the other side (the coin you would cash out into),
  `price_in_counterparty` the pool's own cross rate, `price_usd` its USD
  price. `raw` carries the full CMC pair object, including the bonus aux
  fields (`holders`, `security_scan`, `buy_tax`/`sell_tax`) reserved for
  future factor formulas. `snapshot.source` is `"cmc"` when the CMC quote
  was used, `"dexscreener"` for the fallback.
- `gecko_network` is the GeckoTerminal network id for this pool (e.g. `"eth"`,
  `"base"`), used by `collect-depeg-history` to fetch OHLCV.
- `flags.history_selected` is `true` for the one pool per target selected for
  deep OHLCV collection (the most-liquid price-sane pool with a GeckoTerminal-
  fetchable plain-contract address); `false` for all others. OHLCV itself is not
  in this cache — it lives in
  `collect-depeg-history/data/ohlcv_history.json`.
- Every persisted pool has a non-null `snapshot` (pools without one cannot clear
  the liquidity floor and are never the history pool, so they are dropped).
  `pooled_*` alone being `null` means only the supplemental Dexscreener pass
  failed — the snapshot is otherwise usable.

## On failure

One pool's failure never aborts the run: a pool with no snapshot is dropped
(it cannot affect the score), warned on stderr, and collection continues. A
supplemental (pooled-amounts) failure only costs the `pooled_*` fields. The
cache is written whenever at least one score-relevant pool was persisted; the
script exits non-zero only when none were (no snapshots succeeded, or every
discovered pool was below the liquidity floor and not a history pool — an
existing cache is then preserved) or when no API key was found.

If collection fails or pools come back flagged:

- **No API key found** → create `~/.versusos/.env` as a template (the single
  line `CMC_PRO_API_KEY=` with an empty value, directory created,
  permissions `600`), tell the user to open the file and fill in their key,
  then stop and wait. Never ask the user to paste the key into the chat;
  never echo a key.
- **Vault cache missing** → tell the user to run collect-vault first:
  `python skills/collect-vault/scripts/collect.py`.
- Report the failure/flags to the user; never fabricate pool data.
- A permanently missing snapshot usually means CMC does not index that pool —
  say so rather than retrying.
- If an older cache exists, offer to continue with it, stating its
  `fetched_at` age. Retry only when the user asks.

## Presenting results

After a successful run, show:

1. A summary line: `persisted_pools`/`qualifying_pools` pools kept
   (`dropped_unscored` dropped as score-irrelevant) across `target_tokens`
   targets, `snapshot_ok` snapshots, `history-selected` count, and `fetched_at`.
2. A table of pools: `symbol | chain | dex | price_usd | liquidity_usd |
   pooled_target | pooled_counterparty (symbol)` with flagged pools marked.
3. **Next stage** — when standalone, offer the next step in plain language
   ("Now I can analyze safety to build a recommendation") rather than skill names; under
   orchestration, say nothing (the orchestrator continues).

Always state that this is raw collection — peg classification and safety
judgments happen in the score skill.

## Limitations

- No OHLCV / peg history — use `collect-depeg-history` for the deep OHLCV
  pass (approval-gated; run after the initial scoring step).
- `flags.history_selected` marks only the top-1 most-liquid price-sane pool
  per target **with a GeckoTerminal-fetchable address** (Uniswap-v4 pool ids /
  Curve composites are skipped, so a target with only those gets no history pool).
  Other qualifying pools have `flags.history_selected = false`.
- No market depth — not published off-chain; reserves and the CMC `raw`
  object keep a future depth computation's inputs.
- No peg *classification* — that is a judgment derived downstream from this
  cache.

## References

- `./references/data-sources.md` — endpoints, fields, rate limits, caveats.
- `./config/collect.json` — options: history window, throttle, chain aliases,
  gecko aliases, `counterparty_whitelist`, `abnormal_price_delta` (default 0.5),
  `ds_throttle_seconds` (default 0), `min_pool_liquidity` (default 50000 — the
  score-relevance persist floor; keep equal to score's `pool_liquidity.min_pool_tvl`),
  `cmc_batch_size` (default 100 — CMC address-list chunk size; avoids HTTP 414),
  `cmc_networks` (networks CMC's DEX API serves; chains outside it use the
  Dexscreener fallback — bsc/avalanche are unsupported by CMC).
