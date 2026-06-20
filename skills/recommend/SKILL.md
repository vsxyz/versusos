---
name: recommend
description: >-
  Use when evaluating, ranking, or recommending DeFi yield for a stablecoin
  (e.g. "find USDT yield", "where to earn yield with USDC now"). Confirms the asset, runs the
  fast path (collect → score), then classifies EVM vaults into Conservative /
  Balanced / Aggressive Pick buckets by safety band, hard-excluding disqualified
  vaults (low score, recent exploit, recent depeg, measured dynamic-0) while
  surfacing what was excluded. Shows 2 representative picks per bucket, expands a
  chosen bucket to ≤20, then per-vault detail. Offers opt-in deep/​audit/​context
  enrichments. Stablecoin-only, advisory (read-only).
---

# VersusOS — Recommend (Pipeline Orchestrator)

The entry point for "find me safer stablecoin yield": confirm the asset, make sure
the pipeline data is fresh, run the deductive engine to gate and bucket vaults, and
present the recommendations with the yield/safety trade-off explicit.

Follow the six workflow steps in order, every run. The rules in this file are the
recommendation logic — execute them verbatim; do not substitute judgment for them
(see Boundaries).

## Pipeline

Fast path (deterministic core): `collect → score (initial 0–100) → recommend`, where
`collect` runs `collect-vault → collect-dex`. This is the only thing that runs
automatically.

After that first recommendation, **three opt-in enrichments** can be run in any
combination — then recommend re-runs to fold them in:

- **collect-depeg-history → score (deep):** re-collects OHLCV and re-runs score,
  upgrading the top picks to a 0–200 deep score — **score-affecting; it changes the
  ranking.** Slow (~2 min), approval-gated.
- **research-audit:** graded 0–10 audit verdicts — **advisory; ranking unchanged.**
- **collect-context:** news / Fear & Greed / narratives — **advisory; ranking
  unchanged.**

All three are opt-in and never run without the user choosing them.

## When to use

- The user wants to invest a stablecoin in DeFi yield and cares about safety.
- The user asks to compare, rank, or pick yield vaults for a stablecoin.

Not for: non-stablecoin assets, raw data collection (collect-vault / collect-dex),
score computation (score), or executing deposits/swaps (advisory only — transactions
are permanently out of scope).

## Workflow

**Announce at start (user-facing, in the user's language):** one short,
product-friendly line — the asset + that you're checking for fresh data. No
skill / engine / pipeline-stage names. See **User-facing language** below.
e.g. "Let's find safer USDT yield — first checking the data is current."

### User-facing language (speak value, not internals)

The users are **non-developers**. Everything you *say to them* uses real
web3 / investment vocabulary; concepts that exist only inside VersusOS are spoken
as their value, never by their internal name. The internal names below may still
appear in *these instructions* (you reason with them) — just never echo them to
the user.

**Keep (say to users):** asset names, APY/APR, TVL, liquidity, depeg, audit,
chain, symbol, vault, safety score, and the bucket names
**Conservative / Balanced / Aggressive**.

**Never say to users — speak the value instead:**
- skill / stage / engine names (collect-vault, collect-dex, score, recommend
  engine, collect-depeg-history, research-audit, collect-context) → the action or
  value ("data collection", "safety analysis", "investment strategy", "deep
  analysis", "market trends").
- analysis-mode internals (fast path, deep / Deep step, initial, basis,
  model initial/dynamic, 0–100 / 0–200 scale, normalized_score,
  final_safety_score, score_1/2) → "basic analysis" / "deep analysis (optional
  add-on)"; show **one** safety number as "safety NN/100" (the 0–100 `normalized_score`).
- gate ids (score_floor, recent_exploit, recent_depeg, dynamic_zero, "gate") →
  the plain reason ("below the safety threshold", "recent exploit history",
  "recent depeg", "short-term volatility risk").
- factor name `Dynamic` → "short-term price stability"; field names protocol_audit /
  token_audit → just "audit" (drop the `=NN`).

**Pipeline narration — at most 3 short stage lines (orchestrated run).** When this
skill runs the pipeline (step 2), the sub-skills are invoked **silently** (they
suppress their own announce/handoff under orchestration); *you* narrate, in the
user's language:
1. data refresh → "Collecting the latest market & liquidity data…"
2. scoring → "Analyzing safety from the collected data…"
3. ranking → "Safety analysis is done — now putting together the investment strategy."

**Freshness short-circuit:** if no cache needs refreshing, skip lines 1–2 — go
straight from the start line to the result. Never narrate per-stage skill names or
"X done. Now running Y".

### 1. Confirm the asset — every run

Identify the stablecoin from the request (USDT/USDC/DAI/USD0/USDe…). If the query
names it, state the interpretation ("Proceeding on the basis of USDT") and proceed. If no
asset is given or it is ambiguous, ask which one — never guess.

### 2. Ensure fast-path data (auto-run)

The fast path is the **only** thing that runs automatically — the three
enrichments are opt-in and offered later (step 6). Check
`../score/data/vault_scores.json` and its input caches against the 60-minute
freshness rule, and auto-run what is missing or stale, in order:

1. **collect** — run the `collect` skill, which ensures both fast-path caches
   (`collect-vault → collect-dex`) are fresh, refreshing whichever is missing or
   stale (collect-dex always re-seeds from a just-refreshed vault). Score requires
   both caches, so this cannot be skipped.
2. **score (initial)** — re-run if its cache is missing/stale or `collect` refreshed
   either upstream cache in step 1. This produces an initial 0–100 score based on
   TVL, liquidity, and Contract & Token Safety.

Track what was re-run — it goes in the header summary. If the score output has
`counts.vaults_with_dex_data: 0`, the liquidity factor is 0 for every vault; the
results must say "no DEX data reflected".

Run collect and score **silently** here — narrate only the abstracted stage lines
from **User-facing language** above, never the skills' own announce/handoff output.

### 3. Run the deductive engine

Run the recommender (deterministic — same cache + config = same result):

```
python skills/recommend/scripts/recommend.py --asset <ASSET>
```

It reads `../score/data/vault_scores.json` and `config/recommend.json` and prints
`{asset, counts, buckets, excluded, exclusion_summary, generated_at}`. Use its
numbers verbatim. The engine:

- **Gates (hard-exclude)** on cache-backed conditions only: `score_floor`
  (`normalized_score < 30`), `recent_exploit` (≤ 90d), `recent_depeg` (deep only),
  `dynamic_zero` (deep + measured). Excluded vaults are **not** ranked.
- **Buckets** survivors by `normalized_score`: Conservative ≥ 80 · Balanced 65–79 ·
  Aggressive 50–64 · Avoid 30–<50 (not a pick). Each bucket is sorted by **APR
  within its band**; `reps[...]` are the top `reps_per_bucket` **distinct-project**
  picks (highest-APR pool per project). Avoid is count-only.
- The **† conditions** (protocol TVL < $20M, no audit, lock-up > 30d) are **not**
  gated (uncollected data) — carry them as a verify-before-deposit checklist (§4.4),
  and optionally autonomously look them up for the few displayed picks.

### 4. Present results (fixed order)

**Pick listings are always rendered as a markdown table** (the columns in item 2) —
never as bulleted prose per pick; per-pick factor detail is a compact one-line summary
beneath the table. This applies to every pick listing in this skill's output.

1. **Header** — asset; data freshness (snapshot time, "current as of today" style — not
   raw stage/mode names); `counts` (M of N candidates passed, per-bucket counts). Add one
   plain-language note that this is the **basic analysis** and that **deep analysis**
   (reflecting depeg & short-term volatility) can be added below — never name `initial`,
   `score_floor`, `recent_exploit`, "gate", or the deep step to the user.
2. **Pick buckets** — for **Conservative / Balanced / Aggressive**, render
   **`reps[...]`** (the deduped top-APR distinct-project picks; `display.reps_per_bucket`=2) as a **markdown table** with these
   columns (§5 mirrors these): `| # | Project | Chain | Symbol | Safety | APY | TVL | Notes |`.
   - **Safety** = one number "NN/100" (the 0–100 `normalized_score`; never the 0–200 /
     `final` / `normalized` distinction). **APY** = the headline `yield` (state which
     metric near the table). **TVL** = `tvlUsd`, human-formatted. **Notes** = "USDT derivative"
     when the symbol is not the native asset (the `variant` flag — never the word
     "variant"); "—" when none. Do not use field names (`yield` / `tvlUsd` / `basis` /
     `final_safety_score` / `normalized_score` / `variant`) as visible column headers.
   - **Beneath the table**, one **compact single line per displayed rep** of factor
     detail using the plain labels (contract & token safety / depeg stability / vault TVL /
     pool liquidity / short-term price stability — for `Dynamic` when stale say "reflected after deep analysis").
   - Then the bucket's ordering rationale in plain words, then the existing
     "notable extra picks" callouts. Avoid is a count only, expandable on request.
3. **Exclusion disclosure** (`exclusion_summary`) — a summary line of `by_reason`
   counts in **plain reasons** (below the safety threshold / recent exploit history / recent depeg /
   short-term volatility risk — never the gate ids); **name every `high_apy_callouts` entry**
   with its plain reason ("APY 28% azuro — excluded: below the safety threshold"); list every
   `depeg_excluded` entry with its "(possible pool-data noise)" tag so a false-exclude
   is visible. Offer the full `excluded` list on request.
4. **Verify-before-deposit checklist** — the † items VersusOS does not collect
   (protocol TVL, audit report, lock-up/withdrawal, chain liquidity, bridge, oracle,
   issuer/redemption) with their thresholds. Close with "a safe exit matters more
   than a high APY."
5. **Disclosures** — advisory only / no transactions; that this is the basic analysis and
   deep analysis can refine it (no `initial`/`deep`/`basis` jargon to the user); data
   snapshot timestamps.

### 5. Strategy selection → expand to ≤ 20

After the buckets, ask which strategy to expand (Conservative / Balanced /
Aggressive). On the user's pick, show up to `display.expand_count` (20) from that
bucket (already gated, APR-ordered; the expand list may include multiple pools per
project — only the 2 reps are distinct-project) as a **markdown table** with the **same columns
as §4.2**: `| # | Project | Chain | Symbol | Safety | APY | TVL | Notes |` (Safety = the
single 0–100 number; Notes = "USDT derivative" / "—"). Do not use field names (`yield` /
`tvlUsd` / `basis` / `final_safety_score` / `normalized_score` / `variant`) as visible
column headers.
Then offer per-vault detail on selection (reuse the existing breakdown + the † autonomous
supplement). The three opt-in enrichments (collect-depeg-history / research-audit /
collect-context) are offered exactly as before — after the ranking, never automatic.

### 6. Offer the opt-in enrichments — after the ranking

The three enrichments are **opt-in**: never run without the user choosing them.
After the ranking and disclosures, offer them — the user may pick any combination:

When offering these, name the **value** to the user (deep analysis / in-depth audit
research / market trends), never the skill name.

- **collect-depeg-history — score-affecting.** Slow (~2 min, GeckoTerminal),
  approval-gated. Propose:
  > "Shall I run a deep analysis of the top candidates' depeg & short-term volatility
  > history? (~2 min) The safety scores get more accurate and the ranking may change."
  On approval: run `collect-depeg-history` (default top-N from its config, or a
  user-named set), **re-run `score`**, then re-present from step 3. On decline:
  keep the initial 0–100 ranking and say so.
- **research-audit — advisory.** Ask before running (slow; LLM/web research). On
  approval, run it and attach an audit annotation per pick; on decline or failure,
  continue with "audit not researched". Verdicts never change the ranking.
- **collect-context — advisory.** Quick. Ask before running; on approval, run it
  and add the market-context block; on decline or failure, continue with "no
  market context collected". It never changes the ranking.

After any enrichment, re-run recommend (from step 3) to fold the new data in. None
of these block the pipeline; an advisory enrichment failing is noted, not fatal.

## Upstream caches (read-only)

`vault_scores.json` is the ranking input, but the raw upstream caches may be read
whenever more detail is needed — e.g. a follow-up question about a pick, or
enriching a caution annotation:

- `../collect-vault/data/defillama_yields.json` — raw DeFiLlama vault records
  (full APY breakdown, TVL, pool metadata).
- `../collect-dex/data/dex_pools.json` — DEX pool snapshots + `history_selected`
  / `gecko_network` per pool (OHLCV is in `collect-depeg-history`'s cache).
- `../collect-depeg-history/data/ohlcv_history.json` — per-pool daily + minute
  OHLCV fetched by the opt-in deep step; absent until that step runs.
- `../collect-context/data/context.json` — qualitative market context (news,
  Fear & Greed, narratives); optional — may be absent.
- `../research-audit/data/audit_research.json` — slug-keyed audit verdicts
  (optional; may be absent). Advisory only — never changes the ranking.

Reading them never changes the ranking — they inform explanations and caution
annotations only (see Boundaries).

## Boundaries

- Never recompute or adjust scores; never reorder beyond the rules above. The
  ranking is the deterministic product of these rules — same caches + same config
  = same recommendations.
- Qualitative observations (e.g. a known protocol exploit) may be attached to a
  pick as a caution annotation only — the ordering stands.
- The investment-strategy overlay (`./references/investment-strategy.md`) is
  advisory and educational only: it adds caution annotations and a verify-it-
  yourself checklist, and never changes eligibility, scores, or ordering. Where
  VersusOS lacks a signal the strategy calls for, surface it as a user checklist
  item — never as a silent filter.
- `research-audit` is advisory only — its verdicts are presentation annotations
  and never change `final_safety_score` or the ordering.
- Exclusions are **hard gates** (gate semantics in `references/investment-strategy.md` §3 + `scripts/core/ranking.py`): a gated vault is removed from
  recommendation, never silently — the exclusion disclosure (§4.3) always surfaces
  counts, high-APY callouts, and the depeg list. Gating is deterministic and
  cache-backed; the † conditions are checklist items, not gates.
- `inspect` (inductive) does **not** gate — it shows a matched vault with its gate
  reason raised as a warning (the user asked about *that* token).
- Never fabricate vaults, scores, or rankings.

## On failure

- **collect-vault fails** → follow that skill's On-failure guidance (report
  verbatim, offer the old cache). If proceeding on an old cache, state its age.
- **collect-dex fails** → score cannot run without its cache. Follow that
  skill's failure guidance; if an older DEX cache exists, offer to score on it,
  stating its age. With no DEX cache at all, report and stop — never fabricate.
- **score fails** (an input cache missing) → run the missing collector(s),
  retry once; still failing → report verbatim and stop.
- **Zero scored vaults** → a valid result — report honestly, skip
  recommendations.

## Limitations

- Bucket thresholds and display counts (`reps_per_bucket`, `expand_count`) live in
  `config/recommend.json`; they can be tuned without touching the workflow.
- Recommendation quality is bounded by upstream data freshness and data
  availability (initial vs. deep score).

## References

- `../score/SKILL.md` — the `vault_scores.json` contract this skill reads
  (field names: `final_safety_score`, `normalized_score`, `basis`, `score_1`,
  `score_2`, `vaults_with_history`).
- `./references/investment-strategy.md` — the expert investment-strategy /
  advisory checklist applied as an education overlay (never changes the ranking).
