---
name: collect-vault
description: >-
  Use when collecting or refreshing the stablecoin yield-vault universe — APY, TVL
  and vault metadata from DeFiLlama Yields — filtered to USD-stable singles and
  USDC/USDT-anchored pairs, cached to JSON. First stage of the VersusOS pipeline;
  collection only, no scoring or ranking.
---

# VersusOS — Collect Yield Vaults

Fetch the full DeFiLlama Yields vault set, filter it client-side (tokens, pairs,
min TVL), sort, and cache the snapshot to JSON for the downstream score / recommend
skills.

## Pipeline

Fast path (deterministic core): `collect → score → recommend`, where `collect` (the
fast-path collection orchestrator) runs `collect-vault → collect-dex` — **this skill
is collect's step 1**, and its cache also feeds collect-context and research-audit.
After the first recommendation, three opt-in enrichments deepen the analysis (recommend
orchestrates them): `collect-depeg-history` re-runs score for a 0–200 deep, **re-ranked**
result (**score-affecting**); `research-audit` and `collect-context` add audit and
market-context annotations (**advisory — ranking unchanged**). For an end-to-end
evaluation, the recommend skill orchestrates every stage.

## When to use

- Starting a VersusOS evaluation and the vault cache is missing or stale (see the
  freshness rule under Data cache).
- The user asks to refresh or re-pull yield/vault data for a stablecoin set.

Not for: DEX peg/liquidity data (use collect-dex), scoring (score), or ranking
(recommend).

## Requirements

Python ≥3.10, standard library only — no install and no third-party packages.

## Workflow

**Announce at start.** *Orchestrated (by collect/recommend):* stay **silent** — no
announce, no stage handoff; the orchestrator narrates. *Standalone:* one short
product-friendly line, no skill/stage names — e.g. "Collecting vault yield data…"

Run the collector (paths resolve from the script's own location, so any working
directory works; filters from `./config/collect.json`):

```
python scripts/collect.py [--config <skill-root>/config/collect.json] [--out <skill-root>/data/defillama_yields.json]
```

It fetches all vaults, applies the filters — only single-token vaults that are a
USD stable are kept; two-token pairs and 3+ token vaults are excluded; then min
TVL — sorts (default `apyBase`
desc), and writes the cache. Then present the result as described under
Presenting results.

## Data cache

Output is written relative to this skill folder and read by later pipeline stages
(never re-fetched by them). If a later stage finds it missing, run the collector
first, then retry.

| Data | Path | Produced by |
|------|------|-------------|
| DeFiLlama yield vaults (APY, TVL) | `data/defillama_yields.json` | `python scripts/collect.py` |

**Freshness:** the cache is fresh while its `fetched_at` (UTC) is within
**60 minutes**; older than that is stale — re-run the collector before relying
on it. If the user explicitly asks to use an older cache, do so, but state its age.
The `exploits` block shares this `fetched_at` cadence — it is re-fetched whenever
the collector runs, which over-satisfies DeFiLlama's once-per-day hack updates.

## Output schema

The cache file is the contract downstream skills read:

```json
{
  "source": "defillama_yields",
  "fetched_at": "<UTC ISO-8601>",
  "filters_applied": { "filters": { ... }, "sort": { ... } },
  "counts": { "fetched": <int>, "after_filter": <int>,
              "projects": <int>, "projects_resolved": <int>,
              "projects_with_exploits": <int>, "projects_unresolved": <int>,
              "projects_audited": <int>, "projects_unaudited": <int> },
  "exploits": {
    "available": true,
    "source": "defillama_hacks",
    "fetched_at": "<UTC ISO-8601>",
    "version_propagation": "brand_wide",
    "hacks_total": <int>,
    "by_project": { "<project-slug>": { "exploit_count": <int>, "resolved": true,
                    "parent": "<parent#slug|null>", "events": [ ... ], "flags": [] } },
    "unresolved_projects": [ "<slug>", ... ]
  },
  "audit_triage": {
    "available": true,
    "source": "defillama_protocols",
    "fetched_at": "<UTC ISO-8601>",
    "by_project": { "morpho-blue": { "audits": 2, "audits_label": "audited" } },
    "unresolved_projects": []
  },
  "vaults": [ { "...raw DeFiLlama fields, lossless..." } ]
}
```

- `vaults` is ordered per `filters_applied.sort` (default `apyBase` desc).
- Each vault keeps all raw API fields (~28; key ones: `pool` (id), `project`,
  `chain`, `symbol`, `tvlUsd`, `apyBase`, `apy`, `stablecoin`, `exposure`,
  `ilRisk`). Full field list: `./references/data-sources.md`.
- `exploits` is a **brand-wide** DeFiLlama hack join keyed by each vault's
  `project`: any hack against any version under the same parent protocol is
  counted. Each `events` entry is `{date, name, classification, amount,
  returnedFunds}`. The `max(0, raw − 15 × exploit_count)` penalty is **not**
  applied here — it lands in the score skill.
- On enrichment failure the block is `{ "available": false, "error": "<msg>" }`
  (no `by_project`); the vault data is still written.
- `audit_triage` carries each protocol's free DeFiLlama `audits` code (0=none,
  1=partial, 2=audited, 3=fork) + label, from the same `/protocols` fetch as
  `exploits` (no extra network call). It is a triage signal only — verification
  and 0–10 grading are the optional `research-audit` skill's job.
- `counts.projects_audited` / `projects_unaudited` tally `audits == 2` / `== 0`
  when the triage block is available.

## On failure

The script retries 3× with exponential backoff and exits non-zero on final network
failure **without touching the cache** (fetching happens before any write). A
write-time interruption (disk full, killed process) can still leave a truncated
file — if the cache looks malformed, re-run the collector.

If collection fails:

- Report the failure to the user verbatim.
- If an older cache exists, offer to continue with it, stating its `fetched_at` age.
- Retry only when the user asks.
- Exploit enrichment is **best-effort**: if the DeFiLlama hacks/protocols fetch
  fails, the vault cache is still written with `exploits.available = false` and
  the error message — the run does **not** fail.
- The `audit_triage` block is best-effort like `exploits`: a `/protocols` fetch
  failure sets `audit_triage.available: false` with the error; vault collection
  still succeeds.

Zero vaults after filtering is a valid result, not an error — report the counts.

## Presenting results

After a successful run, show:

1. A summary: `after_filter` / `fetched` counts, `fetched_at`, and the applied
   filters (tokens, pairs, min TVL, sort).
2. A table of the top 10 vaults (or all, if fewer) in the applied sort order:
   `project | chain | symbol | apyBase | tvlUsd`.
3. **Next stage** — when standalone, offer the next step in plain language
   (e.g. "Next I can gather market & liquidity data to build a recommendation") rather than
   skill names; under orchestration, say nothing (the orchestrator continues).

Always state that this is raw collection — the APY ordering is **not** a safety
ranking; scoring happens in the score skill.

## Limitations

- Snapshot only — no per-vault history.
- USD-stable classification is interim (DeFiLlama `stablecoin` flag) until the
  designated-DEX classification (derived from the collect-dex cache) is wired
  into this filter.
- Exploit matching is **ID-based only** (DeFiLlama `defillamaId` /
  `parentProtocolId`). Projects unresolved against `/protocols` are listed in
  `exploits.unresolved_projects` with no penalty; hack rows with no id are
  skipped (no fuzzy name matching).

## References

- `./references/data-sources.md` — endpoints, fields, rate limits, caching.
- `./config/collect.json` — filter preset (tokens, pairs, min TVL, sort).
