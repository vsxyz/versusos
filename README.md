# VersusOS

**VersusOS** is an Agent Skill for **stablecoin-only DeFi yield investing**. It collects
yield and liquidity data for a target stablecoin, assigns a **safety score** to each opportunity,
and ranks/recommends them by APY relative to safety — so you can see the yield/safety trade-off.

## What it is

A read-only assistant that helps you judge **how safe a stablecoin yield vault is**
before depositing. Ask in plain language ("find safer USDC yield") and it sorts vaults into
**Conservative / Balanced / Aggressive** buckets by a transparent safety score — and tells you
which vaults it excluded and why. **EVM chains only** (Ethereum, BNB, Arbitrum, Base, Optimism,
Avalanche, Polygon, …). No `pip install`, no third-party packages — Python ≥3.10
standard library only.

## Quick start

You need **Claude Code** (desktop app or CLI — <https://claude.com/claude-code>) and one free
**CoinMarketCap API key**.

**1 · Install the plugin**

```
/plugin marketplace add vsxyz/versusos
/plugin install versusos@vsxyz
```

Restart Claude Code once after installing. (To update later, see **Updating** below.)

<details><summary>Developer / local install (from a cloned folder)</summary>

```
/plugin marketplace add /path/to/versusos
/plugin install versusos@vsxyz
```
</details>

**2 · Add a free CoinMarketCap API key** (one time — for vault liquidity/price data)

Get a free key at <https://pro.coinmarketcap.com> (the free **Basic** plan is enough). The
easiest way to save it is to ask Claude:

> My CoinMarketCap API key is `<your key>`. Save it to `~/.versusos/.env` as `CMC_PRO_API_KEY=<key>`.

<details><summary>Or do it yourself in a terminal</summary>

```bash
mkdir -p ~/.versusos
echo "CMC_PRO_API_KEY=<your key>" > ~/.versusos/.env
chmod 600 ~/.versusos/.env
```
</details>

The key serves both `collect-dex` (REST) and `collect-context` (direct MCP calls — no MCP
server registration needed). The `CMC_PRO_API_KEY` environment variable also works and takes
precedence. **Never commit a key anywhere.**

**3 · Ask in plain language**

VersusOS understands two kinds of questions:

- **"Where should I deposit?" — find yield**
  > find safe USDT yield vaults right now

  It splits candidates into **Conservative / Balanced / Aggressive** tiers (2 each) and shows
  **which vaults were excluded and why.** Narrow down from there:
  > show me more aggressive ones — expands that tier to up to 20
  > tell me about vault #1 in detail — safety-score breakdown + audit/withdrawal detail

- **"Is this token safe?" — look up by contract address (CA)**
  > is this token safe? 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48

  (That address is USDC; it returns the scored vaults using that token, safety-ranked.)

> 💡 For deeper analysis, just say "yes" to the options Claude offers at the end (depeg history /
> audit verification / market sentiment).

### Understanding the output

| Label | Meaning |
| --- | --- |
| **Conservative / Balanced / Aggressive** | Safety-score tier: ≥80 (safest) / 65–79 / 50–64 (higher yield, higher risk) |
| **Final Safety Score** | 0–100 (0–200 after deep analysis) composite — higher is safer |
| **Excluded (gated)** | Score < 30, a hack in the last ~3 months, or a recent depeg are **auto-excluded** from picks — but the reason is always shown |
| **🚨 / ⚠** | Risk flags to check before depositing (recent hack, thin withdrawal liquidity, …) |
| **Manual checklist** | Items VersusOS can't auto-collect (protocol-wide TVL, official audits, withdrawal limits) — verify these yourself before depositing |

### Before you test

- **Advisory/educational only — not investment advice.** VersusOS **executes no transactions**
  (no wallet connection, deposit, or signing).
- **EVM chains only.** Non-EVM (Solana, Tron, …) is out of scope.
- Every number is a **snapshot at the time it was fetched.**

### Troubleshooting

- **"No API key" message** → recheck step 2 (is the key in `~/.versusos/.env`?). You can ask
  Claude *"check my VersusOS API key setup"*.
- **No results / stale data** → say *"collect fresh data"* or run `/versusos:collect` (~1–2 min).
- **`/versusos:` commands not showing / install failed** → confirm you restarted Claude Code
  after install and that `/plugin install versusos@vsxyz` succeeded.
- **Stuck?** → just ask in plain language, e.g. *"compare safe USDC vaults with VersusOS"*.

### Updating

When a new version is published, refresh the marketplace — the installed plugin updates
automatically:

```
/plugin marketplace update vsxyz
/reload-plugins
```

No restart needed (Claude Code prompts for `/reload-plugins` when an update is applied). To
update automatically on startup instead, run `/plugin` → **Marketplaces** → `vsxyz` → enable
auto-update.

## Example run

Illustrative output from the deterministic recommender on sample data. For `USDT`, 11 candidate
vaults → 7 ranked, 4 excluded:

| Tier | Project | Chain | APY | Safety |
| --- | --- | --- | ---: | ---: |
| Conservative | safeco | Ethereum | 5.0% | 92 |
| Conservative | safeco2 | Base | 6.0% | 84 |
| Balanced | balco | Base | 11.0% | 73 |
| Aggressive | varco | Base | 12.0% | 60 |
| Aggressive | aggro2 | Base | 18.0% | 52 |
| Aggressive | aggro | BSC | 22.0% | 58 |

**Excluded (4) — surfaced, never silently dropped:**

| Project | Chain | APY | Safety | Reason |
| --- | --- | ---: | ---: | --- |
| expco | BSC | 30.0% | 70 | recent exploit |
| lowco | Base | 28.0% | 20 | below score floor |
| depco | Ethereum | 4.0% | 67 | recent depeg |
| dynco | Base | 4.0% | 66 | dynamic liquidity = 0 |

Note `expco` — a 30% APY vault — is excluded for a recent exploit despite the headline yield.
Making that trade-off explicit is the whole point.

## How it works

Each pipeline stage is its own skill; `recommend` orchestrates them end-to-end:

```
★ = CoinMarketCap AI Agent Hub          (one key for both ★: ~/.versusos/.env)

══ Fast path — deterministic core (one step: the `collect` orchestrator) ════════

1 · collect ── runs both collectors in order, freshness-checked ──┐
    │
    ├─ 1a · collect-vault ──────────────────────▶ data/defillama_yields.json
    │       └─ DeFiLlama (no key)
    │            vault APY/TVL universe (~28 raw fields, lossless)
    │            + per-protocol exploit history (hacks) & audit-triage code
    │
    └─ 1b · collect-dex ────────────────────────▶ data/dex_pools.json
            ├─ CMC v4 DEX API ★ (REST)
            │    pool price · liquidity · 24h volume
            │    + aux in raw: holders / security_scan / buy·sell tax
            └─ Dexscreener (no key, supplemental)
                 pooled per-side amounts — the one field pair CMC lacks
                 emits history_selected + gecko_network per pool (for enrichment A)
                 (seeded by 1a's fresh vault cache)

2 · score (initial 0–100) — reads caches only, no network ▶ data/vault_scores.json
    ├─ defillama_yields.json   → tvl factor + vault metadata + exploit penalty
    ├─ dex_pools.json          → liquidity factor + pool metadata
    └─ config/contract_token_safety.json → Contract & Token Safety factor
                                           (static per-vault audit-score mapping)

3 · recommend (1st) — the natural-language entry point / orchestrator
    └─ vault_scores.json → asset → exclusion gate → Conservative/Balanced/Aggressive
       Pick buckets (gate-and-disclose) + trade-offs
       (auto-runs collect → score when caches are missing/stale)

══ Post-recommend opt-in enrichments — any combination, recommend orchestrates ══
   (run after the 1st recommendation, then re-run recommend to fold them in)

A · collect-depeg-history → score (deep)        [SCORE-AFFECTING — re-ranks]
    └─ GeckoTerminal (no key); opt-in, approval-gated, slow (~2 min)
         180-day daily + 12h minute OHLCV for the top-N scored vaults only
         re-run score → matched vaults upgrade to a 0–200 deep score,
         which changes the ranking

B · research-audit                              [ADVISORY — ranking unchanged]
    └─ LLM web research over the top-N protocols by TVL (no key); opt-in
         verify/grade DeFiLlama's audit flag → 0–10 per protocol, cited
         never enters safety_score; recommend surfaces it qualitatively

C · collect-context ★                           [ADVISORY — ranking unchanged]
    └─ CMC MCP server (direct JSON-RPC from the script, no registration); opt-in
         per-coin news · Fear & Greed · trending narratives (all URL-cited)
         feeds recommend's market-context block; never changes the ranking

D · strategy                                    [ADVISORY — doc-only, no script]
    └─ post-recommend; reads score + collect-depeg-history caches (no network)
         produces a self-contained, agent-runnable backtestable strategy spec
         (entry / exit / rebalance rules) → data/strategy_spec.{md,json}
```

Scoring is **hybrid**: a deterministic Python core computes a transparent base score (weights in
`skills/score/config/scoring.json`), and Claude adds documented, bounded qualitative adjustments
on top.

## Structure

Each skill is a self-contained folder under `skills/` — its own `SKILL.md` plus, where
needed, `scripts/` (+ `scripts/core/` helpers), `config/`, and `references/`. No shared
code at the plugin root.

```
.claude-plugin/            # plugin.json + marketplace.json (install metadata)
skills/
  collect-vault/           # vault universe + exploit/audit-triage (DeFiLlama)
  collect-dex/             # pool snapshots — liquidity, price (CMC DEX + Dexscreener)
  collect/                 # fast-path orchestrator: collect-vault → collect-dex (no script)
  score/                   # two-phase safety scoring (0–100 / 0–200)
  recommend/               # natural-language entry point + Pick-bucket gate engine
  collect-depeg-history/   # deep OHLCV history for top-N vaults (opt-in, keyless)
  research-audit/          # LLM audit research (optional, advisory-only)
  collect-context/         # news / Fear & Greed / narratives via CMC MCP (optional)
  strategy/                # backtestable strategy spec (doc-only, no script)
  inspect/                 # token-CA → scored vaults, safety-ranked (advisory)
tests/                     # deterministic tests against fixtures (no network)
```

## Use

- **Natural language (recommended):** ask Claude to find or compare safe stablecoin
  yield (e.g. *"find safer USDC yield vaults"*) — the `recommend` skill picks it up and
  drives the pipeline.
- **Explicit commands:** fast path — `/versusos:collect` (= collect-vault + collect-dex),
  `/versusos:score`, `/versusos:recommend`; post-recommend opt-in enrichments —
  `/versusos:collect-depeg-history`, `/versusos:research-audit`, `/versusos:collect-context`.
  (The individual `/versusos:collect-vault` and `/versusos:collect-dex` still work.)
- **inspect** (`/versusos:inspect`) — inductive entry: resolve a token contract
  address to the scored stablecoin vaults that use it, safety-ranked. Advisory.

`recommend` confirms the **stablecoin asset**, refreshes stale fast-path stages automatically,
then classifies EVM vaults into **Conservative / Balanced / Aggressive Pick buckets** by safety
band (`normalized_score` ≥ 80 / 65–79 / 50–64) — **hard-excluding** disqualified vaults (score
< 30, recent exploit, recent depeg, measured dynamic-0) while **surfacing what was excluded and
why** (counts + high-APY callouts + the depeg list, so nothing is silently dropped). It shows 2
representative picks per bucket, expands a chosen bucket to ≤ 20, then per-vault detail. After
the first ranking it offers the three opt-in enrichments — only `collect-depeg-history` changes
the ranking (0–200 deep score); `research-audit` and `collect-context` annotate only.
**EVM-only**; advisory (read-only) — no transactions.

## Data sources

DeFiLlama Yields (yield, TVL) for the vault universe, and designated DEX pools for the
target coin's market safety — liquidity and current price collected via the
**CoinMarketCap AI Agent Hub** (v4 DEX REST API for snapshots, the CMC MCP server for
qualitative context; Dexscreener fills pooled amounts). **GeckoTerminal** (keyless)
provides 180-day daily and 12h minute OHLCV — fetched on demand by
`collect-depeg-history` for the top-N scored vaults. Peg classification is derived
downstream from this data. DeFiLlama also serves the free hacks catalog and
per-protocol `audits` code, joined per protocol in `collect-vault`; the optional
`research-audit` skill adds LLM web research to verify and grade audits (0–10, cited)
— **advisory-only; verdicts are never applied to `safety_score`**. Separately,
Contract & Token Safety **does** enter `safety_score` (0–15) from a curated static
per-vault mapping (`skills/score/config/contract_token_safety.json`). See each skill's
`references/data-sources.md`.

## Disclaimer

VersusOS is an **educational/research tool, not investment advice.** It is **advisory and
read-only** — it executes no transactions and never connects a wallet. Stablecoins can and do
**depeg**, smart contracts can be exploited, and all figures are point-in-time snapshots that may
be stale or wrong. Do your own research; you are solely responsible for any decisions you make. The
software is provided "as is", without warranty — see [DISCLAIMER.md](./DISCLAIMER.md) and
[LICENSE](./LICENSE).
