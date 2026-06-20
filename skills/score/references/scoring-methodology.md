# Safety Scoring Methodology

How VersusOS turns cached data into a safety score. All constants (point tables,
thresholds) live in `config/scoring.json` so they tune without code changes.

Reproducible and static: every value derives from the caches; recency math uses
the DEX cache `fetched_at` as "now". The point tables and thresholds in
`config/scoring.json` are the canonical formula.

## Two-phase score

**Initial (no history):** `score_1 = ceil2((contract_token_safety + vault_tvl +
pool_liquidity) / 55 × 100)` ∈ [0,100]. (`ceil2` = round up to 2 decimals.)

**Deep (when collect-depeg-history has fetched both daily + minute OHLCV for every
evaluated target):** add `score_2 = ceil2((depeg + dynamic) / 45 × 100)` ∈ [0,100];
the vault then sits on 0–200. depeg/dynamic are additive-only — a poor peg yields a
low score_2, never a deduction below score_1.

**Final = max(0, base − 15 × exploit_count × (max_scale ÷ 100))** where base = score_1
(initial) or score_1 + score_2 (deep). The exploit penalty scales with `max_scale`
(−15 initial / −30 deep) so each exploit is a **uniform −15 on `normalized_score`** in
both phases (without the scaling, going deep would halve the penalty to −7.5).
`normalized_score = ceil2(final / max_scale × 100)` ∈ [0,100] is the uniform safety
axis used for `grade`, **ranking/sort**, and recommend's floors; `final_safety_score`
(native 0–100/0–200) is display-only — never an ordering axis, since the two scales are
not comparable.

| Factor | Pts | Phase | Source |
|--------|----:|-------|--------|
| Contract & Token Safety | 15 | initial | static per-vault mapping (`config/contract_token_safety.json`, `by_pool[poolId].points` = Audit Score = `protocol_audit` 0–10 + `token_audit` 0–5). Unmapped vaults score 0. |
| Vault TVL | 20 | initial | `tvlUsd` step table |
| Pool Liquidity | 20 | initial | Σ USDC/USDT counterparty side over accepted pools (TVL ≥ $50K), step table |
| Depeg | 15 | deep | most-liquid **fetchable** pool's daily **closes** (collect-depeg-history); days whose close held sub-$0.98 deducted by recency. Reading the close (not the intraday low) stops single-tick DEX wicks below peg from false-flagging a genuinely-pegged coin — transient intraday dips are the Dynamic factor's job. |
| Dynamic | 30 | deep | most-liquid **fetchable** pool's 12h minute window (collect-depeg-history); current peg + stateless recovery ladder |

DEX factors (depeg, pool liquidity, dynamic) are computed per matched target
token and the minimum is taken (conservative for LP-pair vaults).

> **Collection coupling.** collect-dex persists only score-relevant pools —
> snapshot liquidity ≥ `min_pool_liquidity` (its config, $50K) or the per-target
> history pool. This is score-neutral as long as that floor equals Pool
> Liquidity's `min_pool_tvl` here: pools below it neither enter the Σ nor carry
> OHLCV. If you lower `min_pool_tvl`, lower collect-dex's `min_pool_liquidity`
> too and re-collect, or the sub-threshold pools this factor wants will be absent
> from the cache.

`exploit_count` is the brand-wide DeFiLlama hacks count for the vault's protocol.
An unclear protocol match applies no penalty and is flagged (`exploit_match`).

## Grade (on normalized_score)

`[80,100] Safe · [65,80) Moderate · [50,65) Aggressive · [30,50) High Risk · [0,30) Avoid`

## Out of scope

Max-deposit sizing and per-vault caps belong to the recommend skill. The on-chain
`maxWithdraw` Vault-Liquidity method and the always-on monitoring daemon are
planned/archived designs and are not implemented.
