---
name: research-audit
description: >-
  Use to research protocol-level audit quality for the scored stablecoin vaults —
  verify DeFiLlama's audits flag, classify RWA vs genuinely unaudited, and grade
  audited protocols 0–10 with cited evidence — caching a slug-keyed verdict file.
  Post-recommend opt-in advisory enrichment (not a fast-path stage); verdicts never
  enter safety_score and never change the ranking — surfaced qualitatively by
  recommend only. LLM/web-research backed, cost-bounded to the top-N protocols by
  TVL, and opt-in from recommend.
---

# VersusOS — Research Audits (LLM, optional)

Turn the free `audit_triage` signal from collect-vault into verified, graded
audit verdicts. Deterministic `plan.py` / `merge.py` scripts bound and record
the work; this SKILL.md dispatches one research subagent per worklisted protocol
under a strict rubric. **Advisory-only** — by design, research-audit is
advisory-only and its verdicts never enter `safety_score`; `recommend` surfaces
them qualitatively.

## Pipeline

Fast path (deterministic core): `collect → score → recommend` (where `collect` runs
`collect-vault → collect-dex`). `research-audit` is one of the **three post-recommend
opt-in enrichments** — run it
after the first ranking, then re-run `recommend` to surface graded audit annotations.
It is **advisory: never a score input, never enters `safety_score`, and never changes
the ranking** (the score-affecting enrichment is `collect-depeg-history`;
`collect-context` is the other advisory one). The fast path proceeds without it and
notes "audit not reflected".

## When to use

- recommend (or the user) wants audit quality reflected and the audit cache is
  missing/stale for the top-N protocols.
- The user explicitly asks to research a stablecoin protocol's audits.

Not for: numeric collection (collect-vault / collect-dex), scoring, or ranking.

## Requirements

Python ≥3.10 stdlib only. No API key. The research step uses web search/fetch via
subagents. Needs a fresh `../collect-vault/data/defillama_yields.json` with an
`audit_triage` block.

## Workflow

**Announce at start:** "VersusOS — research-audit (optional): researching protocol
audit quality for the top-N vaults by TVL."

### 1. Plan the worklist (deterministic)

```
python scripts/plan.py [--vaults ../collect-vault/data/defillama_yields.json] [--top-n 50] [--out-worklist data/audit_worklist.json]
```

This selects the top-N projects by summed TVL, drops entries still fresh under
`ttl_days`, seeds `audit_links`, and writes `data/audit_worklist.json`
(`worklist[]` = `{slug, tvl_usd, audits_triage, track, audit_links}`). If the
worklist is empty, every selected protocol is fresh — skip to step 3.

### 2. Research each worklist item (one subagent per slug, in parallel)

Dispatch a subagent per `worklist` item with the rubric in
`./references/scoring-rubric.md`. Give each subagent: the `slug`, its
`audits_triage` code, its `track` (`verify` for 0/1/3/null, `grade` for 2), and
its `audit_links` seed. Each subagent returns one verdict JSON object (the schema
in the rubric). Collect the objects into a JSON list at `data/verdicts.json` (or
one `data/verdicts/<slug>.json` each).

**Rubric essentials (full text in references):** identify the protocol from slug
+ context; 3–6 web searches; report auditors / dated reports with URLs / bug
bounty / exploit history; **every positive claim needs a fetched source URL**;
unverifiable → `audited: "unknown"` with `score: null`; classify `audits=0` as
`false_negative` / `rwa` / `unaudited`; for `rwa`, gather substitute evidence
(regulator, issuer, attestation URL); emit a 0–10 `score` per the scale.

### 3. Merge verdicts into the cache (deterministic)

```
python scripts/merge.py --verdicts data/verdicts.json [--worklist data/audit_worklist.json] [--out data/audit_research.json]
```

Invalid verdicts are skipped with a warning (never written); valid ones are
folded in with `researched_at`, fresh entries preserved, and coverage finalized.

## Data cache

| Data | Path | Produced by |
|------|------|-------------|
| Research worklist (transient) | `data/audit_worklist.json` | `plan.py` |
| Audit verdicts (slug-keyed) | `data/audit_research.json` | `merge.py` |

**Freshness:** per-entry `researched_at`; an entry is stale after `ttl_days`
(default 7 — audits change slowly, unlike the 60-minute price caches). `plan`
re-lists only stale/missing selected slugs.

## Output schema

The `audit_research.json` shape — each `by_project[slug]` carries `tvl_usd`,
`audits_triage`, `classification`, `audited`, `score` (0–10 or null),
`confidence`, `auditors`, `reports`, `bug_bounty`, `rwa_evidence`,
`exploits_seen`, `sources`, `notes`, `researched_at`.

## On failure

- collect-vault cache missing / no `audit_triage` → `plan` exits non-zero; run
  collect-vault first.
- A subagent cannot verify → it returns `audited: "unknown"`, `score: null`,
  `confidence: "low"`; other slugs still complete (best-effort).
- `audit_links` fetch failure → empty seed, research proceeds.
- Never fabricate auditors, reports, scores, or sources — an unverifiable claim
  is `unknown`.

## Boundaries

- Coverage is intentionally partial (top-N by TVL). Always state what was not
  researched.
- The 0–10 score is the research artifact; by design, research-audit is
  advisory-only — its verdicts never enter `safety_score`; `recommend` surfaces
  them qualitatively.
- Advisory only; read-only.

## References

- `./references/scoring-rubric.md` — the research rubric + verdict schema + the
  0–10 scale.
- `./references/data-sources.md` — DeFiLlama endpoints + caveats.
