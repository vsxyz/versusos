---
name: strategy
description: >-
  Use after a recommend ranking to produce a backtestable strategy spec for a
  stablecoin — explicit entry / exit / rebalance rules instantiated from the
  score + depeg-history caches into a self-contained document another agent can
  backtest directly. Stablecoin-only, advisory (read-only); executes no trades.
---

# VersusOS — Strategy (Backtestable Spec Orchestrator)

Convert the `recommend` Pick-bucket gate rules into an explicit, agent-runnable
strategy specification: entry / exit / rebalance rules instantiated from the
`score` and `collect-depeg-history` caches, a two-axis accounting model
(data-backed peg-risk + assumption-labeled return), and a self-contained output
document that another agent can backtest directly without further inference.
This skill reads caches and writes output; it executes no trades and never
recomputes scores.

## Pipeline

Fast path (deterministic core): `collect → score → recommend`, where `collect`
runs `collect-vault → collect-dex`. This skill is a **post-recommend step**: it
consumes `score`'s `vault_scores.json` (required) and
`collect-depeg-history`'s `ohlcv_history.json` (optional — the time axis).
After the first recommendation, three opt-in enrichments deepen the analysis:
`collect-depeg-history` is score-affecting (upgrades matched vaults to a 0–200
deep score, re-ranks); `research-audit` and `collect-context` are advisory
(ranking unchanged). `strategy` sits after all of those and instantiates a
backtestable spec from whichever caches are present.

## When to use

- After `recommend` (or `score`) to produce a
  backtestable trading-strategy spec with explicit entry / exit / rebalance
  rules that another agent can run from the document alone.
- When the user wants to know the entry/exit/rebalance rules or the two-axis
  backtest accounting model for the current snapshot.

Not for: data collection (`collect-vault` / `collect-dex` / `collect-depeg-history`),
score computation (`score`), Pick-bucket-gated ranking (`recommend`), or
executing deposits/swaps — transactions are permanently out of scope and are
never initiated by this skill.

## Workflow

**Announce at start:** "VersusOS — strategy: instantiating the backtestable
strategy spec from cache."

Follow the six steps in order, every run.

### 1. Confirm bucket

Reuse the Pick bucket already established in the `recommend` session
(Conservative / Balanced / Aggressive). If entered via `recommend`'s workflow,
inherit it without asking again. If invoked standalone without a prior
bucket selection, ask which applies:

- **Conservative** — protect principal; yield is secondary. Band floor 80.
- **Balanced** — best yield per unit of safety. Band floor 65.
- **Aggressive** — maximize yield above the band floor 50.

The per-bucket band floors (80 / 65 / 50) are the lower edges of recommend's Pick
buckets on `normalized_score` (aligns with recommend's gate + bands). No default:
if missing or ambiguous, ask once — never proceed on a guess.

### 2. Check score cache freshness

Check `../score/data/vault_scores.json` against the **60-minute freshness
rule** (compare `generated_at` to the current time):

- **Missing or stale** → stop; tell the user to run `recommend` or `score`
  first to refresh the cache. Never fabricate scores, rankings, or vault data.
- **Fresh** → proceed. Record its `generated_at` for the output header.

### 3. Check the time axis (OHLCV history)

Check whether `../collect-depeg-history/data/ohlcv_history.json` exists:

- **Present** → the backtest will have a full time axis (≤180 daily candles).
  Record its `fetched_at`.
- **Absent** → still emit the complete spec (all rules and parameters are
  defined and complete), but mark throughout:
  > "Backtest window unavailable — run `collect-depeg-history` first; spec is
  > complete but unvalidated against history."
  The spec remains useful as a forward-looking rule set and for live use.

Also check whether `../collect-context/data/context.json` exists. If absent,
note "Fear & Greed unavailable — backtest runs regime-neutral" (the regime rule
is still recorded in the spec for live use).

### 4. Instantiate

Read the caches identified above. Fill in all live values from the caches:

1. **Parameters table** — instantiate each param from its canonical source:
   `floor` from the confirmed bucket's band floor (80 / 65 / 50), `depeg_threshold`
   from `../score/config/scoring.json`, `yield` field preference
   (`apyBase` → `apy` → 0) from `../recommend/SKILL.md`,
   `allocation_table` from the band→weight table in
   `./references/backtest-strategy.md`, keyed to `normalized_score`.
   K=5 and `rebalance_days`=7 are spec defaults (tunable).

2. **Universe selection** — from `vault_scores.json`, apply the bucket's
   band floor on `normalized_score`, rank by the bucket's ordering key (see
   `./references/backtest-strategy.md` § Backtest event loop ordering keys),
   and take top K=5. Record each vault's `pool`, `project`, `chain`, `symbol`,
   `normalized_score`, `yield`, `tvlUsd`, and allocated `weight`.

3. **History resolution** — for each selected vault, resolve its `by_pool` key
   in `ohlcv_history.json` (format: `chain|pool_address|token_address`). Record
   `history_available: true/false` per vault; vaults without a resolvable daily
   series are excluded from historical validation but remain in the live universe.

4. **Create `data/` if absent** — run `mkdir -p skills/strategy/data/` (or
   equivalent) before writing. Then write both output files (see `## Output`).

5. **Golden example** — inline the fixture from
   `./references/backtest-strategy.md` § Golden worked example (2 vaults × 10
   days × one depeg event) with the reference results verbatim. This lets an
   implementing agent verify its arithmetic without re-running the full universe.

### 5. Present summary

After writing the output files, display:

1. **Header** — bucket, pipeline state (caches read, their timestamps),
   data-availability caveats (history present/absent, regime-neutral flag).
2. **Universe** — the K selected vaults: `project | chain | symbol |
   normalized_score | yield | weight | history_available`.
3. **Parameters** — the instantiated Parameters table (param / live value /
   source), matching `./references/backtest-strategy.md` § Strategy parameters.
4. **Data-availability caveats** — repeat any "backtest window unavailable"
   or "regime-neutral" notes here so they are prominent.
5. **Return-axis assumption banner** — mandatory, never omit:
   > "Return axis assumes historical APY ≈ snapshot APY (held constant); the
   > cache has no historical APY time series. Treat `cumulative_return`,
   > `max_drawdown`, and NAV path as illustrative of the strategy's mechanics,
   > not as realized returns."
6. **Advisory / read-only disclosure** — advisory only; not financial advice;
   no transactions are executed; this is a snapshot as of the cache timestamps.

### 6. Next stage / handoff

The saved `data/strategy_spec.md` is the artifact another agent runs. It is
self-contained: the full algorithm from `./references/backtest-strategy.md` is
inlined so the backtesting agent needs no other file. Say:

> "The instantiated spec has been written to `skills/strategy/data/strategy_spec.md`
> (prose + inlined algorithm) and `skills/strategy/data/strategy_spec.json`
> (machine-readable params + universe). A backtesting agent can run the full
> backtest from `strategy_spec.md` alone."

If the history cache was absent, remind the user:
> "To validate the spec against 180-day history, run `collect-depeg-history`
> then re-run `strategy`."

## Output

Two files written to `skills/strategy/data/` (gitignored; the directory is
created if absent):

| File | Content |
|------|---------|
| `data/strategy_spec.md` | Full instantiated spec in prose: live Parameters table, selected universe, the complete algorithm from `./references/backtest-strategy.md` inlined verbatim, golden example with reference numbers, metric definitions, assumption banner, and disclosures. Self-contained — no other file needed to run the backtest. |
| `data/strategy_spec.json` | Machine-readable snapshot of params + universe (schema: `source`, `generated_at`, `bucket`, `reference_time`, `inputs`, `parameters`, `universe`, `data_availability`, `assumptions` — schema documented in `./references/backtest-strategy.md`). |

The methodology and algorithm that the output inlines lives at
`./references/backtest-strategy.md` (static; never changes between runs).

## Boundaries

- **Advisory / read-only.** Never executes transactions; never sends orders;
  never deposits or withdraws. Transaction execution is permanently out of scope.
- **Never recomputes scores.** Reads `normalized_score` and all vault fields
  verbatim from the `score` cache; makes no adjustments.
- **Never fabricates.** If the score cache is missing or stale, stop. If a
  vault has no history pool, flag it — never invent OHLCV data or scores.
- **Never reorders beyond the rules.** The universe selection and weight
  assignment follow the deterministic rules in `./references/backtest-strategy.md`
  verbatim; no qualitative overrides.
- Same caches + same bucket = same spec (fully reproducible).

## On failure

| Situation | Handling |
|---|---|
| `vault_scores.json` missing or stale | Stop; tell the user to run `recommend` or `score` first. No fabrication. |
| `ohlcv_history.json` absent | Emit the complete spec; mark "backtest window unavailable — run `collect-depeg-history` first; spec complete but unvalidated against history." |
| Vault `basis == "initial"` or no daily series | Excluded from historical validation; flagged as `history_available: false`; may remain in the live universe. |
| Zero vaults pass the bucket's band floor | Report honestly; emit the spec with an empty universe and a note; never lower the floor silently. |
| `context.json` absent | Backtest runs regime-neutral; note "Fear & Greed unavailable". The regime rule is still recorded in the spec for live use. |
| Vault matches multiple history pools | Use the evaluated target's most-liquid pool — the same pool `score` uses for its depeg factor. |

## References

- `./references/backtest-strategy.md` — the static executable methodology:
  data contract, strategy parameters, signal definitions, the deterministic
  backtest event loop (pseudocode), two-axis accounting model, metric
  definitions, the golden worked example, and determinism rules. The output
  `data/strategy_spec.md` inlines this document verbatim.
- `../score/SKILL.md` — the `vault_scores.json` contract this skill reads
  (`normalized_score`, `final_safety_score`, `basis`, `apyBase`, `apy`,
  `tvlUsd`, `factors.depeg`, `exploit_count`, `dex_pools_matched`).
- `../recommend/SKILL.md` — the bucket definitions, band floors, the gate's
  `score_floor`, ordering keys, and `yield` field preference that feed this
  skill's universe selection and parameter instantiation.
