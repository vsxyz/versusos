# Audit Research Rubric + 0–10 Score

Reuse verbatim for every research subagent. The source-URL-required and
unknown-forced clauses are what keep it safe (graded against DeFiLlama, no
hallucination).

## Task

Given a protocol `slug`, its DeFiLlama `audits_triage` code, its `track`, and an
`audit_links` seed, determine its audit status and grade it 0–10.

1. Identify the protocol from the slug + any context (the seed links help).
2. Run 3–6 web searches. Prefer official docs, auditor sites/repos, GitHub
   `audits/` dirs, Immunefi/bug-bounty pages.
3. Report, each with a fetched source URL: auditors; dated audit reports; bug
   bounty (platform + max payout); exploit history (distinguish contract flaw vs
   oracle/config vs credit default vs key compromise); protocol shutdown if any.
4. **Every positive claim needs a fetched source URL.** No verifiable evidence →
   `audited: "unknown"`, `score: null`, `confidence: "low"`.
5. Classify a `audits_triage == 0` protocol as:
   - `false_negative` — audits exist but DeFiLlama's flag missed them.
   - `rwa` — regulated TradFi product where smart-contract audit doesn't apply;
     gather substitute evidence (`rwa_evidence`: `{regulator, issuer,
     attestation_url}`).
   - `unaudited` — genuinely no audit.
   For `track == "grade"` (code 2) confirm and grade quality.

## 0–10 score scale

- `0` — verified unaudited (`audited: "no"`). A genuinely undeterminable protocol
  is `audited: "unknown"` with `score: null`, never `0`.
- `3–5` — a single audit, or partial coverage.
- `6–8` — multiple reputable auditors, recent relative to contract upgrades.
- `9–10` — extensive audits + a sizeable bug bounty + clean exploit history.
- **RWA** — score on substitute evidence (reserve attestations + regulatory
  status), not smart-contract audits.

## Return one JSON object

```json
{
  "slug": "<the slug>",
  "classification": "audited|false_negative|rwa|unaudited|partial|fork|unknown",
  "audited": "yes|no|unknown",
  "score": 0,
  "confidence": "high|medium|low",
  "auditors": ["..."],
  "reports": [{"firm": "...", "date": "YYYY-MM", "url": "https://..."}],
  "bug_bounty": {"platform": "...", "max_usd": 0, "url": "https://..."},
  "rwa_evidence": null,
  "exploits_seen": 0,
  "sources": ["https://..."],
  "notes": "..."
}
```

`bug_bounty` and `rwa_evidence` are `null` when absent. `score` is `null` only
when `audited` is `unknown`. `sources` must be non-empty for any positive claim.
