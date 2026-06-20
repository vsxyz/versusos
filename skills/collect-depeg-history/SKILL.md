---
name: collect-depeg-history
description: >-
  Use to deep-collect depeg (daily) and dynamic (minute) OHLCV history from
  GeckoTerminal for the top-N already-scored stablecoin vaults — the slow,
  rate-limited data split out of collect-dex. Opt-in and approval-gated; run only
  after the user agrees, then re-run score to fold the history into a 0–200 deep
  safety score. Reads cached data, writes its own ohlcv_history.json.
---

# VersusOS — Collect Depeg/Dynamic History (opt-in, slow)

GeckoTerminal OHLCV is the rate-limited bottleneck, so it is collected here on
demand for **only the top-N finalists**, not the whole universe. This keeps the
base pipeline fast.

## Pipeline

Fast path (deterministic core): `collect → score (initial 0–100) → recommend` (where
`collect` runs `collect-vault → collect-dex`). `collect-depeg-history` is the
**score-affecting** one of the three
post-recommend opt-in enrichments: on approval, `collect-depeg-history → score (deep)
→ recommend (final)` upgrades the top picks to a 0–200 deep score and **re-ranks**
them. (The other two enrichments — `research-audit`, `collect-context` — are advisory
and leave the ranking unchanged.) Orchestrated by recommend.

## When to use

- recommend (or the user) has an initial ranking and wants the depeg/dynamic
  factors reflected for the top candidates.
- The user explicitly asks to deep-analyze specific vaults' peg history.

**Approval-gated:** this step is slow (GeckoTerminal throttle + rate limits).
Never run it without explicit user approval.

Not for: snapshot/liquidity collection (collect-dex), scoring (score), ranking
(recommend).

## Requirements

Python ≥3.10 stdlib only. **No API key** (GeckoTerminal is keyless). Needs a fresh
`../score/data/vault_scores.json` (the ranking) and `../collect-dex/data/dex_pools.json`
(pool addresses + `gecko_network` + `history_selected`).

## Workflow

**Announce at start:** "VersusOS — collect-depeg-history (opt-in): deep-collecting
depeg/dynamic OHLCV for the top-N vaults."

```
python scripts/collect.py [--top-n 10] [--refresh] [--scores ...] [--dex ...] [--out ...]
```

It selects the `history_selected` pools of the top-N ranked vaults, fetches daily
(`history_days`) and minute (`minute_window_hours`) OHLCV per pool — throttled
`throttle_seconds` (default 6.0s) before **every** call so the two calls never
burst, with a Retry-After-aware 429 retry sized to the 60-second window — and
writes `data/ohlcv_history.json`. Then re-run `score` to produce deep (0–200)
scores. Pools whose address is not a plain contract address (Uniswap v4 pool ids,
Curve composites — GeckoTerminal 404s on these) are skipped, not fetched (counted
as `skipped_non_address`).

**Resume (default):** pools already collected (both candle lists non-null) are
reused from the existing `data/ohlcv_history.json`, not re-fetched — so a re-run
only fills the gaps, makes far fewer calls (keeping clear of GeckoTerminal's
30 calls/min limit), and never regresses a good cache. Pass `--refresh` to ignore
the cache and re-fetch every pool.

## Data cache

| Data | Path | Produced by |
|------|------|-------------|
| Per-pool daily+minute OHLCV | `data/ohlcv_history.json` | `python scripts/collect.py` |

Shape: `{source, fetched_at, history_window_days, minute_window_hours, counts:
{targets, daily_ok, minute_ok, skipped_non_address}, by_pool: {"<chain>|<pool>|<token>": {chain,
pool_address, token_address, ohlcv_daily, ohlcv_minute}}}`. A failed fetch leaves
that candle list `null` (score treats the pool as having no history → stays on the
initial 0–100 score).

## On failure

- Missing `vault_scores.json` / `dex_pools.json` → exits non-zero; run score (and
  collect-dex) first.
- No `history_selected` pools for the top-N → exits non-zero, cache not written.
- A single pool's fetch failing (rate limit) warns and continues; that pool's
  candle list stays `null`.
- A pool whose address is not GeckoTerminal-fetchable (Uniswap v4 pool id / Curve
  composite) is skipped with a warning, not fetched; its candle list stays `null`
  (counted under `skipped_non_address`).

## References

- `./references/data-sources.md` — GeckoTerminal endpoints + rate-limit notes.
