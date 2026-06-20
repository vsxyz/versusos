# Data Sources — collect-dex

External APIs the collector uses, with the live-verified caveats the
implementation depends on.

Snapshots are CMC-primary (keyed); the discovery and pooled-amounts source is
Dexscreener (free, key-less). The discovery seed comes from the collect-vault
cache. OHLCV history is not fetched here — see `collect-depeg-history` for the
GeckoTerminal OHLCV client and its data-sources notes.

## DeFiLlama `/pools` — discovery seed (collect-vault cache)

Pool targets are **not** statically configured. Instead, each vault's
`underlyingTokens` field (contract addresses per chain) is read from the
collect-vault cache (`skills/collect-vault/data/defillama_yields.json`). One
seed per distinct `(chain, token_address)` across all cached vaults,
deduplicated and lowercased; vaults on unsupported chains (absent from
`chain_aliases`) are skipped. The DeFiLlama `/pools` response populates
`underlyingTokens` in the vault cache — the collect-vault collector fetches it.

## Dexscreener — discovery + pooled amounts

Free public API, no key.

### Pool discovery

- **Endpoint:** `GET https://api.dexscreener.com/token-pairs/v1/{chainId}/{tokenAddress}`
  — one call per seed token; responses are a bare JSON array (no wrapper
  object). Returns every pool on that chain containing the token, with both
  sides identified.
- **Fields used for discovery:** `pairAddress`, `baseToken.address`,
  `baseToken.symbol`, `quoteToken.address`, `quoteToken.symbol`, `dexId`.
  Counterparty address is lowercased and checked against `counterparty_whitelist`
  (config) — only USDC/USDT-paired pools are kept.
- **Rate limit:** ~300 requests/min; responses are server-cached ~30 s.
- **Caveats:** default `Python-urllib` User-Agent is blocked with HTTP 403
  (`core/http.py` always sends a custom UA); returned `pairAddress` is
  checksummed — all address matching is done lowercased.

### Pooled per-side amounts (all discovered pools)

- **Fields used:** `liquidity.base` / `liquidity.quote` (pooled token amounts
  per side, token units); orientation determined by which side holds the target
  token address.
- The same pair objects returned by discovery are reused for pooled amounts —
  no second Dexscreener call is needed per pool.

### Fallback snapshot (CMC-unindexed pools)

When CMC's `quotes/latest` does not return a quote for a discovered pool,
the Dexscreener pair object builds the full snapshot instead
(`snapshot.source = "dexscreener"`). `priceUsd` is the base asset's USD
price; `priceNative` is the base priced in quote units — both sides are
derivable from these. `liquidity.usd` is the pool's USD liquidity. The
fallback snapshot is field-compatible with a CMC snapshot.

## CoinMarketCap v4 DEX API — pool snapshots (primary)

The data layer of the CMC AI Agent Hub (REST path).

- **Endpoint:** `GET https://pro-api.coinmarketcap.com/v4/dex/pairs/quotes/latest?network_slug=<slug>&contract_address=<addr1,addr2,…>&aux=holders,security_scan,buy_tax,sell_tax&skip_invalid=true`
  — one batched call per chunk of up to `cmc_batch_size` (config, default 100)
  pool addresses per chain (live-verified: one call returned multiple pairs,
  1 credit each). Chains with more pools than the chunk size span several calls.
- **Auth:** `X-CMC_PRO_API_KEY` header; the key is resolved at runtime from
  the `CMC_PRO_API_KEY` env var or the dotenv key file `~/.versusos/.env`
  (`CMC_PRO_API_KEY=<key>`; free signup at https://pro.coinmarketcap.com).
  Never commit the key.
- **Fields used:** `quote[0].liquidity` (pool liquidity, USD),
  `quote[0].price` (base asset USD price), `quote[0].price_by_quote_asset`
  (base priced in quote units — both sides derivable),
  `quote[0].volume_24h`, `base_asset_*`/`quote_asset_*` (identity + addresses
  for target-side matching), aux `holders`/`security_scan`/`buy_tax`/`sell_tax`
  (ride along in `snapshot.raw` for future factor formulas).
- **Caveats (live-verified 2026-06-11):**
  - `network_slug` is accepted case-insensitively; responses echo it
    capitalized ("Ethereum"). Slug values live in `chain_aliases` in
    `config/collect.json`.
  - Batch responses can silently drop unindexed pools — the collector then
    builds the snapshot from the Dexscreener pair instead. A pool that still has
    no snapshot is dropped from the cache (it cannot clear the liquidity floor or
    be a history pool, so it feeds no score factor).
  - **Request-URI length (HTTP 414, live-verified 2026-06-16):** a chain's full
    address list in one GET overflows the URI on large chains (e.g. Ethereum).
    The collector chunks the list into `cmc_batch_size` addresses per call; a
    failed chunk warns and is skipped (its pools fall back to Dexscreener), so a
    long list never costs the whole chain.
  - **Non-address pool ids (HTTP 400, live-verified 2026-06-16):** Dexscreener
    `pairAddress` is sometimes a 32-byte pool id (`0x` + 64 hex, e.g. Uniswap v4)
    or a hyphen-joined Curve/registry composite; CMC's `contract_address` 400s on
    these. The collector filters them out of the CMC request (`cmc.is_contract_address`)
    and serves those pools from the Dexscreener fallback snapshot instead. The
    same constraint governs the **history pool**: `discovery.history_targets` only
    marks a plain-contract-address pool as `history_selected`, because
    GeckoTerminal (collect-depeg-history) 404s on these ids — so the per-target
    history pool is always one that can actually be deep-collected.
  - **Unsupported networks (HTTP 400 "network is not supported", live-verified
    2026-06-16):** CMC's DEX API does not serve every chain — `bsc` and
    `avalanche` 400 with this message (the body confirms it; ethereum/base/
    arbitrum/polygon work). The `cmc_networks` allowlist (config) lists the
    served networks; chains outside it skip the CMC call and use the Dexscreener
    fallback snapshot (discovery still covers them, so they stay scored). Update
    the allowlist if CMC's coverage changes.
  - **No per-side pooled token amounts** — Dexscreener fills those (above).
  - **OHLCV endpoints unusable on the current plan:** `/v4/dex/pairs/ohlcv/historical`,
    `ohlcv/latest`, `trade/latest`, `listings/quotes` and `networks/list` all
    returned instant HTTP 500s (elapsed ≈0 ms, no credits charged) across
    param variants and retries, while `quotes/latest` and `spot-pairs/latest`
    worked. Likely plan gating surfaced as 500. OHLCV history is handled by
    the `collect-depeg-history` skill via GeckoTerminal.
  - **`spot-pairs/latest` cannot discover by token (live-verified 2026-06-16):**
    It requires a known dex slug; the `base_asset_*`/`quote_asset_*`/
    `liquidity_min`/`sort` filter params are silently ignored and it returns
    no per-side pooled amounts. Discovery therefore stays on Dexscreener
    token-pairs; `quotes/latest` remains the snapshot source for the discovered
    pool addresses.

## Rejected alternatives (and when to revisit)

- **CMC x402 path:** key-less pay-per-request ($0.01 USDC on Base), but only
  4 endpoints and no OHLCV historical — and it needs a funded wallet. Not
  worth the dependency for a collector that already has a key.
- **GeckoTerminal-only:** no per-side reserve split (`reserve_in_usd` only) —
  fails the pooled-amounts requirement.
- **Curve official API** (`api.curve.finance`, `prices.curve.finance`):
  free, key-less, multi-year OHLC and per-pool balances for Curve pools. Add a
  client here if the delivered mapping leans on Curve pools that CMC and
  Dexscreener do not index.
- **DeFiLlama coins API** (`coins.llama.fi`): multi-year token price history,
  but cross-venue **aggregate** — violates the designated-DEX principle; only a
  labeled fallback if a >180-day window is ever required.
