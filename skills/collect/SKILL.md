---
name: collect
description: >-
  Use to collect or refresh all fast-path data needed for scoring in one step —
  vault yields (collect-vault) and DEX pool snapshots (collect-dex) — running the
  two collectors in dependency order under the 60-minute freshness rule, so the DEX
  pool discovery seed is always the fresh vault cache. The fast-path collection
  orchestrator; run it before score, or let recommend drive the whole pipeline.
  Stablecoin-only and advisory (read-only).
---

# VersusOS — Collect (Fast-Path Collection Orchestrator)

One step to get both fast-path caches fresh: run `collect-vault`, then `collect-dex`
(which seeds its pool discovery from the vault cache). This removes the two-invocation
chore and guarantees collect-dex always discovers from the just-refreshed vault set.
It runs no collection logic of its own — it sequences the two collector skills, every
run, in order.

## Pipeline

Fast path (deterministic core): `collect → score → recommend`, where **this skill
(`collect`)** runs `collect-vault → collect-dex`. `score` then consumes both caches and
`recommend` orchestrates the whole pipeline (delegating its collection phase to this
skill). After the first recommendation, three opt-in enrichments deepen the analysis:
`collect-depeg-history` (score-affecting, re-ranks) plus advisory `research-audit` and
`collect-context` (ranking unchanged).

## When to use

- The user wants fresh vault + DEX data (e.g. before scoring) without invoking the two
  collectors by hand.
- A later stage reports a missing/stale vault or DEX cache and both should be refreshed
  together.

Not for: scoring (score), ranking (recommend), or the opt-in enrichments
(collect-depeg-history / research-audit / collect-context).

## Requirements

Python ≥3.10 stdlib only. `collect-dex` needs a CoinMarketCap API key (`~/.versusos/.env`
or the `CMC_PRO_API_KEY` env var); `collect-vault` needs no key.

## Workflow

**Announce at start.** *Orchestrated by recommend:* stay **silent** — emit no
announce or stage handoff; the orchestrator narrates (see recommend's
**User-facing language**). *Standalone:* one short product-friendly line in the
user's language, no skill/stage names — e.g. "Refreshing the latest market & liquidity data…"

Check each cache against the **60-minute freshness rule** and run, in order:

1. **collect-vault** — run that skill if `../collect-vault/data/defillama_yields.json`
   is missing or stale (DeFiLlama, keyless, ~5s).
2. **collect-dex** — run that skill if `../collect-dex/data/dex_pools.json` is missing or
   stale, **or if collect-vault was just refreshed in step 1** (so discovery always seeds
   from the fresh vault cache). CMC + Dexscreener, ~75s.

Track what was (re)run for the summary. If both caches are already fresh, say so and skip.

## Presenting results

1. A summary line: which stages re-ran (or "both fresh — skipped"), each cache's
   `fetched_at`, and headline counts (vault `after_filter`; dex
   `persisted_pools`/`qualifying_pools` and `history-selected`).
2. **Next stage** — when standalone, offer the next step in plain language
   ("Now I can analyze safety to build a recommendation") rather than skill names; under
   orchestration, say nothing (the orchestrator continues).

## On failure

- **collect-vault fails** → follow that skill's On-failure guidance; never run collect-dex
  on no/old vault data without stating it.
- **collect-dex fails** (no CMC key, or no qualifying pools) → follow that skill's
  On-failure guidance; report the DEX cache is missing and stop before score (score needs
  both caches).
- Never fabricate data; use an older cache only if the user asks, stating its age.

## References

- `../collect-vault/SKILL.md`, `../collect-dex/SKILL.md` — the two collectors this skill
  sequences (sources, output schemas, failure modes).
