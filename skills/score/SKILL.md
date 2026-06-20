---
name: score
description: >-
  Use when computing safety scores for collected stablecoin yield vaults. Joins each
  vault to its DEX pools, computes the points model into a two-phase score
  (initial 0–100 from TVL/liquidity/Contract & Token Safety; deep 0–200 when
  collect-depeg-history history is present), applies the exploit penalty, and caches
  the ranked result. Stage of the VersusOS pipeline; reads cached data only, never the
  network.
---

# VersusOS — Score Vault Safety

Read the cached collect-vault and collect-dex data, join each vault to its
associated DEX pools (1:N), compute the five-factor points model into a
two-phase score (initial 0–100 or deep 0–200 when depeg/dynamic history is
available), apply the exploit penalty for a final score and grade, and cache the
ranked scores for the recommend skill.

## Pipeline

Fast path (deterministic core): `collect → score → recommend`, where `collect` runs
`collect-vault → collect-dex` — **this skill consumes collect's two caches**
(collect-vault + collect-dex). After the first recommendation, three opt-in
enrichments deepen the analysis: `collect-depeg-history` is **score-affecting** —
re-running this skill with its OHLCV present upgrades matched vaults to a 0–200 deep,
**re-ranked** score; `research-audit` and `collect-context` are **advisory** (never
score inputs — ranking unchanged). For an end-to-end evaluation, the recommend skill
orchestrates every stage.

## When to use

- The vault cache exists and the user wants safety scores or a safety ranking.
- The recommend skill needs `data/vault_scores.json` and it is missing or stale.

Not for: collecting data (collect-vault / collect-dex) or producing the final
APY-to-safety recommendation (recommend).

## Requirements

Python ≥3.10, standard library only — no install and no third-party packages.

## Workflow

**Announce at start.** *Orchestrated (by recommend):* stay **silent** — no
announce, no stage handoff. *Standalone:* one short product-friendly line, no
skill/stage names — e.g. "Analyzing safety from the collected data…"

Run the scorer (paths resolve from the script's own location, so any working
directory works; point tables from `./config/scoring.json`):

```
python scripts/score.py [--config ...] [--vaults ...] [--dex ...] [--history ...] [--out ...]
```

It reads the collect-vault and collect-dex caches (both required), optionally merges
the collect-depeg-history OHLCV cache, matches each vault's token symbols and chain
to the DEX pools, computes the five-factor points model into an initial 0–100
score (or deep 0–200 when history is present), applies the exploit penalty for a
final score and grade, sorts descending by `normalized_score` (the uniform safety
axis), and writes the cache.
Then present the result as described under Presenting results.

## Data cache / inputs

Inputs are the upstream skills' caches (never re-fetched here; their 60-minute
freshness rules apply). Output is written relative to this skill folder.

| Data | Path | Produced by |
|------|------|-------------|
| Per-vault safety scores (ranked) | `data/vault_scores.json` | `python scripts/score.py` |

Both vault and DEX caches are required — if either is missing, the script exits
without writing; run the missing collector first, then retry. A vault that
matches no DEX pools still gets scored on TVL only (its DEX factors are 0).

`../collect-depeg-history/data/ohlcv_history.json` is an **optional** input: when
present, the scorer merges daily + minute OHLCV into the pool index and vaults whose
evaluated target(s) all have both candle series score **deep** (0–200); vaults
without history stay **initial** (0–100). Absent or inaccessible → all vaults score
initial. Run collect-depeg-history (approval-gated) then re-run score to upgrade the
top picks to deep.

`../collect-context/data/context.json` is an **optional** input (not read by
the script): when present and fresh, its items feed the context annotations under
Presenting results; when absent, skip them and state "no market context collected".

Contract & Token Safety comes from the static per-vault mapping in
`config/contract_token_safety.json` (`by_pool[poolId]`; this file is the source of
record for these audit scores). Each record carries `points` (Audit Score 0–15, the value that
enters the score) plus the split `protocol_audit` (0–10) and `token_audit` (0–5),
where `points == protocol_audit + token_audit`. A vault with no mapping entry scores
0. `research-audit` is **not** a score input — it is a post-recommend advisory
enrichment surfaced by `recommend`.

## Output schema

The cache file is the contract the recommend skill reads:

```json
{
  "source": "versusos_score",
  "generated_at": "<UTC ISO-8601>",
  "model": "points_v1",
  "inputs": {
    "vaults":   { "path": "...", "fetched_at": "..." },
    "dex":      { "path": "...", "fetched_at": "..." },
    "history":  { "path": "...", "fetched_at": "..." }
  },
  "counts": { "vaults_scored": 0, "vaults_with_dex_data": 0, "vaults_with_history": 0 },
  "scores": [
    {
      "pool": "...", "project": "...", "chain": "...", "symbol": "...",
      "evaluated_token": "USD0", "tvlUsd": 0, "apyBase": 0, "apy": 0,
      "score_1": 0, "score_2": null, "basis": "initial", "max_scale": 100,
      "raw_safety_score": 0, "exploit_count": 0, "exploit_penalty": 0,
      "final_safety_score": 0, "normalized_score": 0, "grade": "Avoid",
      "factors": {
        "contract_token_safety": { "points": 0, "token_audit": 0, "protocol_audit": 0 },
        "depeg": 0, "vault_tvl": 0, "pool_liquidity": 0,
        "dynamic": { "points": 0, "stale": true }
      },
      "flags": { "dynamic_stale": true, "exploit_match": "unmatched" },
      "dex_pools_matched": 0
    }
  ]
}
```

- `scores` is ordered by `normalized_score` descending (the uniform safety axis;
  higher = safer), with `final_safety_score` breaking ties.
- `final_safety_score` ranges 0–100 (initial) or 0–200 (deep) — a native-scale
  **display** value, never an ordering axis (the two scales are not comparable).
- `score_1` ∈ [0,100] is always present; `score_2` ∈ [0,100] is non-null only for deep vaults.
- `basis`: `"initial"` or `"deep"`. `max_scale`: 100 (initial) or 200 (deep).
- `normalized_score = ceil2(final / max_scale × 100)` ∈ [0,100] — the uniform axis for `grade`, **ranking/sort**, and recommend's floors.
- A vault with `dex_pools_matched: 0` scores on TVL only (its DEX factors are 0 —
  `depeg`, `pool_liquidity`, and `dynamic` each contribute 0 points).

## On failure

- Vault cache missing: the script exits non-zero without writing — run
  collect-vault first, then retry.
- DEX cache missing: the script exits non-zero without writing — run collect-dex
  first, then retry.
- Zero vaults in the input is a valid result, not an error — report the counts.

## Presenting results

After a successful run, show:

1. A summary: `vaults_scored`, `vaults_with_dex_data`, `vaults_with_history`,
   `generated_at`, and `model`.
2. A table of the top 10 vaults (or all, if fewer) by `normalized_score`:
   `project | chain | symbol | basis | final_safety_score | normalized_score | grade | apyBase | tvlUsd`,
   with the factor breakdown available on request. Surface any `dynamic.stale`
   warnings, `exploit_match: "unmatched"` flags, and vaults with `basis: "initial"`
   (incomplete depeg/dynamic data) as caveats below the table.
3. **Context annotations (optional)** — if the collect-context cache is fresh,
   attach to affected vaults a cited annotation (e.g. a depeg headline for the
   vault's stablecoin). Annotations are presentation-only: `final_safety_score`
   in the cache is never modified, and every annotation must cite a cached item's
   URL. No citable item → no annotation.
4. **Next stage** — when standalone, offer the next step in plain language
   ("Now I can put together an investment strategy and recommendation") rather than skill names; under
   orchestration, say nothing (the orchestrator continues).

Safety ordering is not the final recommendation — APY-to-safety ranking happens
in the recommend skill.

## Limitations

- Per-vault deposit caps and max-deposit sizing are out of scope — those belong to
  the recommend skill.
- Contract & Token Safety (0–15) comes from a static per-vault mapping (`config/contract_token_safety.json`, `points` = Audit Score, split into `protocol_audit` 0–10 + `token_audit` 0–5); vaults absent from the mapping score 0. `research-audit` does not feed the score.
- Depeg and Dynamic factors (0–45 combined, forming `score_2`) require the optional
  `collect-depeg-history` step; without it, every vault is `initial` (0–100 scale).
- A vault stays `initial` if any evaluated target is missing either daily or minute
  OHLCV (deep requires both for every target).
- Vault→pool matching is by token symbol + chain; pools of a pair vault's partner
  token count toward the same vault.

## References

- `./references/scoring-methodology.md` — factor definitions, point tables, final formula.
- `./config/scoring.json` — tunable point tables and thresholds (no code changes needed).
