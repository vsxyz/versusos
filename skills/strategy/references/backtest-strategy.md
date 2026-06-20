# Backtest Strategy Methodology

**VersusOS stablecoin yield strategy — static executable specification.**

This document is self-contained and agent-executable: an implementing agent must be able to
run the full backtest simulation from this file alone, with no further inference and without
reading other files. It is the canonical specification of the algorithm. Tunable
constants are identified in § Strategy parameters, each citing its canonical source so values
remain in sync with their owners. The golden worked example (§ Golden worked example) lets any
implementation verify its arithmetic against a machine-verified reference run.

---

## Data contract

### Inputs

| Input | Path | Shape | Role |
|---|---|---|---|
| Daily OHLCV | `skills/collect-depeg-history/data/ohlcv_history.json` → `by_pool[key].ohlcv_daily` | ≤180-candle series `[ts, open, high, low, close, volume]`, **newest-first**, USD | the only time axis — peg/price only |
| Safety scores | `skills/score/data/vault_scores.json` → `scores[]` | snapshot @ `generated_at` | held constant: universe selection, APY, TVL, liquidity |
| Market context | `skills/collect-context/data/context.json` → Fear & Greed | snapshot | regime input — **live-only** (no historical series) |

### Field units

- `ohlcv_daily` candle layout: `[ts, open, high, low, close, volume]`, **newest-first**,
  ≤180 elements. `ts` is a Unix millisecond timestamp. Prices are in USD.
- `vault_scores.json` carries: `normalized_score` (uniform 0–100 axis), `final_safety_score`
  (display-only), `basis` (`"initial"` / `"deep"`), `apyBase` / `apy` (percent, e.g. `5.2` =
  5.2% — divide by 100 for accrual), `tvlUsd`, `factors.depeg`, `factors.pool_liquidity`,
  `exploit_count`, `dex_pools_matched`.

### Pool key and vault → pool resolution

The `by_pool` key format is `chain|pool_address|token_address`. For each vault, resolve its
daily series using the evaluated target's most-liquid pool — the same pool the `score` skill
uses for its depeg factor. A vault with no resolvable daily series is **excluded from
historical validation** (kept in the live universe, flagged as `history_available: false`).

### Time alignment

- `ohlcv_daily` is stored newest-first → **reverse to oldest → newest** before iterating (see
  § Determinism rules).
- All snapshot fields (`normalized_score`, APY, TVL) are held constant across the entire
  backtest window at their snapshot values.
- Reference "now" = the newest `ohlcv_daily` timestamp across all selected vaults.

### Missing-data handling

| Situation | Handling |
|---|---|
| Vault has no `ohlcv_daily` series | Excluded from historical validation; flagged |
| `basis == "initial"` | Excluded from historical validation; flagged |
| Day absent for a held vault | Forward-fill last known close; vault not held before its first candle |
| `ohlcv_history.json` absent entirely | Emit spec; mark "backtest window unavailable — run `collect-depeg-history` first" |

---

## Strategy parameters

Each row cites its canonical source to prevent drift.

| Param | Default value | Canonical source |
|---|---|---|
| `bucket` | one of `Conservative` / `Balanced` / `Aggressive` | user (recommend step 1) |
| `floor` (on `normalized_score`) | band floors 80 / 65 / 50 by bucket (lower edges of the Pick buckets) | `skills/recommend/SKILL.md` |
| `yield` | `apyBase` if present, else `apy`, else 0 (percent) | `skills/recommend/SKILL.md` |
| `K` (universe size) | 5 | this spec (tunable) |
| `rebalance_days` | 7 | this spec (tunable) |
| `depeg_threshold` | 0.98 | `skills/score/config/scoring.json` |
| `allocation_table` (by `normalized_score`) | ≥80 → 25% · [65,80) → 15% · [50,65) → 7.5% · [30,50) → 2.5% · <30 → 0% | this spec (allocation bands, keyed to `normalized_score`) |
| `accrual` | simple daily `(yield/100) / 365`, held constant | this spec (assumption — see § Accounting model) |

**Weight renormalization:** selected-K weights from the allocation table are used as-is
when their sum ≤ 1. If the sum exceeds 1 (more than 4 vaults at the 25% band), weights are
scaled proportionally so Σ weight ≤ 1. The remainder is always cash.

---

## Signal definitions

### Depeg event (historical)

For each held vault `v` on day `d`: if `ohlcv_daily[v][d].low < depeg_threshold` then:
- Exit at that day's `close`.
- Realize a markdown of `max(0, 1.0 − close_d)` against the held position value.
- Move proceeds (position value × close_d) to cash.
- Record a `depeg_exit(v, d)`.

### Safety-downgrade exit

Folded into the depeg trigger: because `normalized_score` is a held-constant snapshot, there
is no per-day score change. The safety floor is applied once at universe selection (t0).

### Regime (live-only)

`Fear & Greed < 25` → raise `floor` (de-risk the live universe). With no historical F&G
series in cache, the backtest runs **regime-neutral** (floor unchanged throughout). The rule
is recorded here for live use when `context.json` is present.

---

## Backtest event loop

Deterministic pseudocode — implement exactly:

```
series  = {v: reverse(ohlcv_daily[v])}            # oldest -> newest
axis    = sorted(unique(union of candle days across selected v))
ranked   = sort(scores, by bucket ordering key desc)           # recommend's ordering
universe = [v in ranked if normalized_score(v) >= floor][:K]   # snapshot, t0
weights  = renormalize(allocation_table[normalized_score(v)] for v in universe)
holdings = {v: weights[v]}; cash = 1 - sum(weights); NAV = 1.0

for d in axis (oldest -> newest):
    for v in holdings: holdings[v] *= (1 + (yield(v)/100)/365)      # daily accrual
    for v in list(holdings):
        c = candle(v, d)  (forward-fill last close if absent; skip before first candle)
        if c.low < depeg_threshold:                                # depeg exit
            cash += holdings[v] * c.close; del holdings[v]; record depeg_exit(v, d)
    if d is a rebalance boundary (every rebalance_days from t0):       # reset weights vs current NAV
        nav      = cash + sum(holdings.values())
        elig     = [v in universe if not currently_depegged(v, d)]     # latest available low >= threshold
        w        = renormalize(allocation_table[normalized_score(v)] for v in elig)
        holdings = {v: nav * w[v] for v in elig}; cash = nav - sum(holdings.values())
    NAV = cash + sum(holdings.values()); record NAV, drawdown
report(strategy metrics) vs baseline
```

**Ordering key by bucket:**

| Bucket | Primary ordering key |
|---|---|
| `Conservative` | `normalized_score` desc → `yield` desc → `tvlUsd` desc → file order |
| `Balanced` | `yield × normalized_score / 100` desc; tie → `tvlUsd` desc → file order |
| `Aggressive` | `yield` desc; tie → `tvlUsd` desc → file order |

**Baseline:** naive max-APY buy-and-hold — equal-weight top-K by `yield` (safety ignored),
no depeg exit, accrues APY daily and absorbs full peg markdowns at `close`. The baseline
demonstrates the strategy's risk-avoidance value by showing what happens when safety signals
are ignored.

---

## Accounting model

### Risk axis (data-backed)

`depeg_exits`, `peg_max_deviation`, and `depegs_avoided` vs baseline. These values derive
entirely from the historical `ohlcv_daily` series — no assumptions.

### Return axis (assumption-labeled)

> **ASSUMPTION BANNER — mandatory when presenting return-axis results:**
> "Return axis assumes historical APY ≈ snapshot APY (held constant); the cache has no
> historical APY time series. Treat `cumulative_return`, `max_drawdown`, and NAV path as
> illustrative of the strategy's mechanics, not as realized returns."

The NAV path accumulates daily APY accrual minus realized peg markdowns on depeg exits.
Both strategy and baseline return-axis outputs carry this banner.

---

## Metrics

Exact definitions — implement precisely:

| Metric | Definition |
|---|---|
| `cumulative_return` | `NAV_final / 1.0 − 1` |
| `max_drawdown` | `max over d of (peak_≤d − NAV_d) / peak_≤d` where `peak_≤d = max(NAV_t for t ≤ d)` |
| `depeg_exits` | count of depeg-triggered exits in the strategy |
| `depegs_avoided` | `(#days baseline held a vault with low < depeg_threshold)` − `(same count for strategy)` |
| `peg_max_deviation` | `max over all (v, d) where v is held by strategy of (1.0 − low_{v,d})` |

Rounding: monetary values to 1e-6 (6 decimal places); report percentages to 2 decimal
places (ceil2 convention as in `score`).

---

## Golden worked example

### Fixture

- **2 vaults:** A and B.
- **Bucket:** Balanced (band `floor = 65`).
- **Parameters:** K = 5, `rebalance_days` = 7, `depeg_threshold` = 0.98.
- **10 daily candles** (oldest → newest, format `(low, close)`):
  - Vault A: `(1.00, 1.00)` × 10 — holds peg throughout.
  - Vault B: `(1.00, 1.00)` × 5, then `(0.95, 0.96)` on day 5, `(0.94, 0.95)` on day 6,
    then `(0.99, 1.00)` × 3 — depegs on days 5–6, recovers.
- **Scores:** A `normalized_score` = 82, `yield` = 6.0%, `tvlUsd` = $50M;
  B `normalized_score` = 68, `yield` = 9.0%, `tvlUsd` = $10M.
- **Allocation table:** ≥80 → 25%, [65,80) → 15%.

### Results

The reference implementation of the § Backtest event loop on this fixture produces:

```
Selection (balanced key yield×ns/100): universe = [B, A]  (B 6.12 > A 4.92)
Weights t0: B 0.15, A 0.25   |   cash 0.60
depeg_exits = 1   |   exposed_days: strategy 1 vs baseline 2   |   depegs_avoided = 1
peg_max_deviation = 0.05
Strategy:  nav_final = 0.994697 | cumulative_return = -0.005303 | max_drawdown = 0.005928
Baseline:  nav_final = 1.002057 | cumulative_return =  0.002057
```

### Interpretation

This fixture is a **mechanics-verification example, not a performance claim**. The honest
takeaway: the depeg-exit rule exits B at close 0.96 on day 5 (realizing a small markdown),
while the baseline holds through both depeg days. The strategy ends at −0.53% vs the
baseline's +0.21%, but cuts exposed days from 2 to 1 and reduces max drawdown from the
baseline's full mark-to-market markdown to 0.59%. The depeg-exit rule trades expected return
for tail-risk reduction — exiting a transient depeg realizes a small loss but avoids the
worst-case outcome had the peg not recovered.

An implementing agent's run on the same fixture **must reproduce the numbers above exactly**.
If any value differs, the implementation's event loop or accounting does not match this spec.

---

## Determinism rules

1. **Time direction:** `ohlcv_daily` is stored newest-first — always reverse to
   oldest → newest before iterating the event loop.
2. **Date axis:** build the axis as the union of all selected vaults' candle timestamps;
   sort ascending. A vault is **not held before its first candle** — skip accrual and depeg
   checks for that vault on days before its first data point.
3. **Forward-fill:** when a held vault has no candle for a given day, use its last known
   close as a price proxy; apply daily accrual normally.
4. **Reference "now":** the newest `ohlcv_daily` timestamp across all selected vaults.
   Used to determine "currently depegged" at a rebalance boundary and for live recency
   display. The backtest loop itself is purely chronological — it detects per-day depeg
   events; it does not re-score the depeg factor.
5. **Rounding:** monetary values to 1e-6; percentages to 2 decimal places (ceil2).
6. **Tie-breaks** (reuse recommend's): primary key tie → larger `tvlUsd` → file order.
7. **Excluded vaults:** vaults without a daily series, or with `basis == "initial"`, are
   excluded from historical validation and flagged. They may still appear in the live
   universe (with `history_available: false`).
8. **Rebalance boundary:** day index `d` (0-based, oldest = 0) is a rebalance boundary when
   `d > 0 and d % rebalance_days == 0`. Reallocation resets weights against the current NAV
   (mark cash + holdings → re-derive renormalized allocation weights for the eligible set →
   `holdings[v] = nav × w[v]`, remainder to cash), per the event loop above.
9. **Universe order:** the emitted `universe[]` (in `strategy_spec.json` and the instantiated
   spec) preserves the bucket ranking order (descending) used for selection, so consumers
   may rely on its index order.
