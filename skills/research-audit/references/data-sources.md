# Data Sources — research-audit

## DeFiLlama protocol audit fields

- `GET https://api.llama.fi/protocols` (bulk) — `audits` code per protocol;
  collected upstream by collect-vault as the `audit_triage` block (this skill
  reads it from the vault cache, not the network).
- `GET https://api.llama.fi/protocol/{slug}` (per-slug) — adds `audit_links`
  (report URLs). Fetched here best-effort as a research seed only; failure → no
  seed, research proceeds.

## Why LLM research (not the field alone)

The `audits` field is self-reported listing metadata: false negatives (same
family scored differently), RWA mismatch (regulated TradFi reads as `0`), and no
quality dimension (one no-name report and 18 reputable ones both read `2`). The
rubric verifies and grades it.

## Web research

Auditor sites/repos, official protocol docs, GitHub `audits/` directories,
Immunefi and other bug-bounty platforms. Every positive claim is backed by a
fetched source URL (rubric rule).
