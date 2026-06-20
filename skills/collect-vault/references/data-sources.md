# Data Sources — Yield Vaults (DeFiLlama)

External data the collect-vault skill collects, with notes on endpoints, fields, and
handling. The designated-DEX sources (peg, depeg history, liquidity) are documented in
the collect-dex skill (`../collect-dex/references/data-sources.md`).

## DeFiLlama — Yields

Public, no API key required.

> **Terminology:** DeFiLlama's API calls yield vaults "pools". VersusOS says **vault**
> for yield opportunities and reserves **pool** for DEX liquidity pools; raw API
> URLs and field names (`pool`, `poolMeta`) are kept verbatim.

- **All vaults:** `GET https://yields.llama.fi/pools`
  - Returns the full vault set (~16k); fields per vault include: `pool` (id),
    `project`, `chain`, `symbol`, `apy`, `apyBase`, `apyReward`, `tvlUsd`,
    `stablecoin` (bool), `ilRisk`, `exposure`, `predictions`, `apyPct1D/7D/30D`,
    `apyMean30d`, `mu`, `sigma`, `count`, `outlier`, `underlyingTokens`,
    `rewardTokens`, `poolMeta`, `volumeUsd1d/7d`.
  - **No server-side filtering:** query params (`token`, `minTvl`, `chain`,
    `stablecoin`, …) are ignored — the endpoint always returns everything. The
    `defillama.com/yields?…` URL is the frontend; its filtering is client-side.
    VersusOS filters client-side with its own rule (see `scripts/core/filters.py`
    and `config/collect.json`): only single-token vaults pass, and only when the
    token is a USD stable; two-token pairs and 3+ token vaults are excluded;
    then min TVL. USD-stable classification for the single-token filter is the
    **designated DEX**'s responsibility; **interim**, it is still resolved from the
    Yields `stablecoin` flag until the designated-DEX classification (derived from
    the collect-dex cache) is wired in.
- **Vault history:** `GET https://yields.llama.fi/chart/{pool}` — historical
  APY/TVL for one vault (not collected in v1; reserved for stability checks).

## DeFiLlama — Hacks + Protocols (exploit history)

Public, no API key required. Joined per protocol and merged into the vault cache
as the `exploits` block. Brand-wide: any hack against any version under the same
parent protocol counts.

- **Hacks:** `GET https://api.llama.fi/hacks` — top-level **list** (~555 entries,
  2016→present). Per-row fields used: `date` (unix int), `name`, `classification`,
  `amount` (USD at hack time), `returnedFunds`, `defillamaId` (int | absent),
  `parentProtocolId` (`"parent#<slug>"` string; key absent when null).
- **Protocols:** `GET https://api.llama.fi/protocols` — top-level **list**
  (~7.7k). Fields used for the join: `slug`, `id` (**string**), `parentProtocol`
  (`"parent#<slug>"` | null).
- **Join:** vault `project` slug → `/protocols` (`id`, `parentProtocol`) → a
  single **brand key** (`parent#<slug>`, or `id#<int>` for standalone protocols).
  Each hack row also resolves to one brand key, so matching never double-counts
  the rows that carry both ids. `id` (str) vs `defillamaId` (int) is normalized.
- **Skipped:** hack rows with no `defillamaId` and no `parentProtocolId` (~226,
  mostly CEX/chain/wallet targets) — no fuzzy name matching, per policy.
- **CMC has no equivalent** (entity-model mismatch — exploit history attaches to
  protocols, which CMC does not model).

## DeFiLlama — Protocols (audit triage)

`GET https://api.llama.fi/protocols` (free, no key) — already fetched for the
exploit join. Each protocol carries an `audits` field: `0`=none, `1`=partial,
`2`=audited, `3`=fork-of-audited (sometimes a string; coerced to int, else
`null`/`unknown`). Joined by `slug` to each vault's `project` and merged as the
top-level `audit_triage` block. The field is **self-reported listing metadata**
with known false negatives and no quality dimension — the `research-audit` skill
verifies and grades it.

## Handling notes

- **Rate limits:** DeFiLlama endpoints are public but rate-limited — fetch once per run
  and **cache** raw responses to JSON (this skill's collect stage writes these).
- **Determinism:** scoring/ranking read cached JSON, never the network, so they are
  reproducible and testable against `tests/fixtures/`.
