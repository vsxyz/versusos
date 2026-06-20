---
name: inspect
description: >-
  Use when the user gives a specific token contract address (CA) and asks whether
  it is safe or where to use it (e.g. "is this CA safe?", "is this USDe safe?",
  pasting a 0x token address). The inductive entry: resolves the token CA to the
  already-scored stablecoin vaults that use it (via the collect-vault
  underlyingTokens index joined to the score cache) and presents them
  safety-ranked, reusing recommend's per-vault breakdown and flags. If the token
  is not in the scored universe, reports "out of coverage" honestly. Token-CA
  centric (v1); a vault/pool CA may fall through to out-of-coverage.
  Stablecoin-only, advisory (read-only); never executes transactions.
---

# VersusOS — Inspect (Inductive Token-CA Entry)

The entry point for "is this contract safe?": take a token contract address,
identify the stablecoin vaults that use it, and present their existing safety
analysis. inspect **reads caches and never recomputes scores** — it filters the
scored universe to one token and presents it the way `recommend` does.

## Pipeline

inspect sits on the deductive fast path (`collect → score`) but enters from a
token CA instead of a bucket selection: `collect → score → inspect`, where `collect`
runs `collect-vault → collect-dex`. It reuses `../score/data/vault_scores.json`
(the ranking input) and `../recommend/SKILL.md`'s presentation rules.

## When to use

- The user supplies a token contract address and asks if it is safe, or which
  vaults use it.
- Not for: a bucket-based "find me yield" request (that is `recommend`);
  raw collection (`collect-vault`/`collect-dex`); score computation (`score`);
  executing deposits/swaps (advisory only — transactions are out of scope).

## Workflow

**Announce at start:** "VersusOS — inspect: resolving the token address against the
scored universe."

### 1. Extract the address (+ optional chain)

From the user's message, extract the EVM contract address(es) (`0x` + 40 hex) and
any chain hint ("0x… on base", "on Arbitrum"). If the message has no `0x…` address,
ask for one — never guess. A non-EVM address (e.g. a Solana/Tron base58 mint) is
**out of v1 EVM scope**: say so and do not pass it to the resolver (`resolve.py`
also rejects it, returning it under `rejected_non_evm`). v1 is **token-CA
centric**: if the user calls it a "vault" address, proceed anyway (it is matched
as a token) and note that a vault contract may not match.

### 2. Ensure the scored universe is fresh (reuse recommend step 2)

Check `../score/data/vault_scores.json` against the **60-minute freshness rule**.
Missing or stale → run the `collect` skill then `score` (initial), exactly as
`recommend` does, before resolving. (The first run collects the whole
universe — same cost as a first `recommend` run.) Deep depeg/dynamic stays the
opt-in `collect-depeg-history` enrichment.

### 3. Resolve

Run the resolver (one address shown; pass `--chain` only if the user gave one):

```
python skills/inspect/scripts/resolve.py --addresses <0x…> [--chain <chain>]
```

It prints `{"query", "count", "matches"}` JSON; `matches` are score records
(safety-ranked, `scored: true`) or `{…, scored: false}` for a matched-but-unscored
vault. Use these numbers verbatim.

### 4. Present (fixed order)

- **`count == 1`** → a single detailed analysis (the inductive form): summary verdict
  (project / chain / symbol, `final_safety_score` + `normalized_score`, `grade`,
  `yield`, `tvlUsd`) + score breakdown (`factors`: contract_token_safety / depeg /
  vault_tvl / pool_liquidity / dynamic). inspect does **not** gate — if the vault
  would trip a gate (`score_floor` / `recent_exploit` / `recent_depeg` /
  `dynamic_zero`), raise that reason as a prominent ⚠ warning rather than
  excluding it, following `../recommend/SKILL.md` §3 (the gate) + §4 (presentation).
- **`count > 1`** → the same token legitimately backs several vaults (e.g. a major
  stablecoin). Present the safest first: top **3** detailed picks + a top-**10**
  table, in `normalized_score` order — the matched subset of recommend's output.
- **`scored: false`** on a match → "identified, no score (not in the score cache)"; never
  invent a score.
- No bucket prompt — inductive is "is this safe?", so results are
  safety-ranked.

### 5. Out of coverage (`count == 0`)

- input was non-EVM (in `rejected_non_evm`) → "this address is not an EVM address, so
  it is out of v1 scope (Solana/Tron and other non-EVM chains unsupported)." Do not name or score it.
- chain known **and** `naming_enabled` → name the token:
  `python skills/inspect/scripts/naming.py --chain <chain> --token <0x…>`. Report:
  "this token ([symbol], [chain]) is outside VersusOS coverage — no scored stablecoin
  vault." If it prints `unidentified` → "address could not be identified (out of coverage)."
- chain unknown → do not probe every chain; report "not in the cache — tell me the
  chain and I'll try to identify it."

### 6. Mandatory disclosures — never omit

- Advisory only — not financial advice; no transactions are executed.
- Token-CA centric (v1); a vault/pool contract may not match → out of coverage.
- Scores reflect TVL + liquidity + Contract & Token Safety; depeg/dynamic appear
  only after the opt-in deep step (`basis: "deep"`).
- The data is a snapshot as of the cache timestamps.

### 7. Offer the deep enrichment — after the analysis

If a matched vault's `basis` is `initial`, offer `collect-depeg-history` → `score`
(deep) for it, exactly as `recommend` does, then re-present from step 3.

## Boundaries

- Never recompute or adjust scores; never reorder beyond the safety ranking. Same
  caches + same address = same output.
- Never fabricate a vault, score, or symbol. A matched-but-unscored vault is
  reported as such; an unresolvable address is reported as out of coverage.
- Advisory only — transactions are permanently out of scope.

## On failure

- **Score/vault cache missing** → `resolve.py` returns non-zero; run the missing
  collector(s) + `score` (step 2), retry once; still failing → report and stop.
- **naming.py fails / prints `unidentified`** → report the token as unidentified;
  the out-of-coverage result still stands.

## References

- `./references/data-sources.md` — what is read and the v1 scope.
- `../recommend/SKILL.md` — the gate (§3) + per-vault presentation (§4) reused
  here; inspect raises a vault's gate reason as a warning instead of excluding it.
- `../score/SKILL.md` — the `vault_scores.json` contract (`normalized_score`,
  `final_safety_score`, `basis`, `factors`, `grade`).
