# inspect — data sources

inspect is the **inductive entry**: given a token contract address, it reports
the safety of the stablecoin vaults that use it. It reads caches only; it never
re-scores and (except for the optional naming call) never touches the network.

## Read (never written)

- `../collect-vault/data/defillama_yields.json` — the **CA index**: each vault's
  `underlyingTokens` is matched against the user's token address; the matched
  `pool` ids join to the score cache.
- `../score/data/vault_scores.json` — the safety scores (`normalized_score`,
  `final_safety_score`, `basis`, `factors`, `grade`, `tvlUsd`, `apyBase`/`apy`),
  keyed by `pool`. inspect presents these verbatim.

## Network (optional, keyless)

- **Dexscreener token-pairs** (`naming.py`) — names an out-of-coverage token
  (its symbol) for the "not covered" report. Used only when a token CA matches
  no scored vault and a chain is known. No API key.

## Scope (v1)

- **Token CA only.** A vault/pool contract address that is not a value in any
  vault's `underlyingTokens` falls through to "out of coverage".
- **Stablecoin-only, EVM covered chains** (`config/inspect.json` `covered_chains`).
- Inherits the deductive gaps: Protocol TVL, lock-up/withdrawal terms, and
  audit-as-exclusion are not collected; inspect shows only the fields `score`
  produces. Depeg/Dynamic factors appear only on `basis == "deep"` (after the
  opt-in `collect-depeg-history`).
