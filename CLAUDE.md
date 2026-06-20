# VersusOS

An Agent Skill for **stablecoin-only DeFi yield investing**. VersusOS collects
yield and liquidity data, assigns a **safety score** to each opportunity, and ranks/recommends
vaults by APY relative to that safety score.

## Goal

1. Collect data for a target stablecoin: DeFiLlama Yields (APY, TVL) + discovered DEX pools (USDC/USDT-paired, found via Dexscreener token-pairs) snapshotted via the CoinMarketCap v4 DEX API (price, depeg history, liquidity) + optional qualitative context via CMC MCP (news, Fear & Greed, narratives).
2. Derive safety insights (depeg history, liquidity, TVL, audit & exploit history, …) into a single **safety score**.
3. Rank / recommend yield opportunities by **APY-to-safety**.

## Status

Ten-skill plugin (one skill per pipeline stage, plus the `collect` and `recommend`
orchestrators and the `inspect` / `strategy` entry skills) — the full pipeline is implemented. The **fast path** is a deterministic
core that the `collect` skill orchestrates in one step (it runs `collect-vault` →
`collect-dex`): `collect-vault` collects vault yields (DeFiLlama); `collect-dex`
collects pool snapshots via the CMC v4 DEX API with
Dexscreener (pooled amounts), emitting `history_selected` + `gecko_network` per pool
but no longer fetching OHLCV, and persisting only score-relevant pools (snapshot
liquidity ≥ `min_pool_liquidity` $50K, or the per-target history pool — the rest feed
no factor and are dropped); `score` computes two-phase safety scores (0–100 initial;
0–200 deep when OHLCV history is present) with Contract & Token Safety sourced from a
**static per-vault mapping** (`config/contract_token_safety.json`); `recommend`
applies deterministic gate-and-disclose Pick-bucket rules via `scripts/recommend.py`
+ `config/recommend.json` (asset → exclusion gate → Conservative/Balanced/Aggressive
buckets, excluded picks surfaced).
After that first recommendation, **three opt-in enrichments** can run in any
combination (recommend orchestrates them, then re-runs recommend to fold them in):
`collect-depeg-history` (opt-in, keyless, approval-gated) deep-collects daily+minute
GeckoTerminal OHLCV for the top-N scored vaults into `data/ohlcv_history.json` and is
**score-affecting** — re-running `score` upgrades matched vaults to the 0–200 deep
scale and re-ranks them; `research-audit` LLM-researches protocol audit quality into a
slug-keyed cache, and `collect-context` gathers news / Fear & Greed / narratives via
the CMC MCP server (spoken directly from its collector script, no MCP registration),
both **advisory-only — they never enter `safety_score`; recommend surfaces them
qualitatively** and the ranking is unchanged.
Installed via `/plugin` only (no drop-in copy
path). **Advisory only (read-only)** — no transactions; transaction execution
(vault deposits, DEX purchases) is permanently out of scope.
The `inspect` skill adds the **inductive entry**: a token CA resolves to the
already-scored stablecoin vaults that use it (advisory; reuses the score cache
and recommend presentation; no re-scoring).

## Key Decisions

- **Runtime:** Claude Code (local CLI) — full Python/Bash/network/filesystem.
- **Scoring:** hybrid — deterministic Python computes data + a base safety score; Claude applies
  bounded, documented qualitative adjustments and explanation.
- **Packaging:** one skill per pipeline stage, each a self-contained folder owning its
  scripts/config/references (self-contained skill folders); `recommend` is the orchestrator
  and natural-language entry point. Commands: `/versusos:<skill-name>`.

## Layout

Each `skills/<name>/` folder is self-contained; `tests/` and `.claude-plugin/` live at
the repo root.

- `.claude-plugin/` — `plugin.json` + `marketplace.json`; skills are auto-discovered. Keep both `version` fields in sync.
- `skills/collect-vault/` — implemented. `SKILL.md`; `scripts/collect.py` (the CLI entrypoint — the only runnable script); `scripts/core/` (`filters`, `defillama`, `exploits`, `audit_triage` — imported as `from core import ...`, PEP 420 namespace pkg, no `__init__.py`; a `__main__` guard makes a direct run exit non-zero); `config/collect.json`; `references/data-sources.md`. Applies an **EVM-only filter** (non-EVM chains excluded at collection time). Cache output: `skills/collect-vault/data/` (gitignored) — yields plus top-level `exploits` and `audit_triage` blocks.
- `skills/collect-dex/` — implemented. `SKILL.md` + `references/data-sources.md`; `config/collect.json` (`counterparty_whitelist` per chain, `chain_aliases`, `gecko_aliases`, `abnormal_price_delta`, `min_pool_liquidity` — the score-relevance persist floor); `scripts/collect.py` (entrypoint — `--vaults` takes the collect-vault cache, seeding targets from `underlyingTokens`); `scripts/core/` (`discovery.py` — pure vault→seeds + token-pairs filter + top-1 history selection; `dexscreener.py` — `fetch_token_pools` token-pairs client; `cmc.py`, `dexpools.py` — shaping/snapshot + score-relevance persist filter). **Does not fetch GeckoTerminal OHLCV** — it emits `history_selected` + `gecko_network` per pool so `collect-depeg-history` can fetch OHLCV for the top-N vaults. The static `config/dex_pools.json` pool mapping is retired; pools are discovered at runtime. Cache output: `skills/collect-dex/data/dex_pools.json` (gitignored). Key from `~/.versusos/.env` or the `CMC_PRO_API_KEY` env var (never committed).
- `skills/collect/` — implemented (orchestrator, **no script**). `SKILL.md` only — the fast-path collection orchestrator: runs `collect-vault` → `collect-dex` in one invocation under the 60-minute freshness rule (collect-dex always re-seeds from a just-refreshed vault). Owns no collection logic and has no `scripts/`/`config/`; `recommend` delegates its collection phase here. Reachable as `/versusos:collect`.
- `skills/collect-depeg-history/` — implemented (opt-in, keyless). `SKILL.md` + `references/data-sources.md`; `config/collect.json` (`top_n`, `throttle_seconds`, `history_days`, `minute_window_hours`); `scripts/collect.py` (entrypoint); `scripts/core/` (`geckoterminal.py` — OHLCV client with 429 retry + contract-address validation that skips Uniswap-v4/Curve pool ids GeckoTerminal 404s on; `targets.py` — pure top-N pool selection). Deep-collects daily+minute GeckoTerminal OHLCV for the top-N scored vaults only; approval-gated (slow). Cache output: `skills/collect-depeg-history/data/ohlcv_history.json` (gitignored). **No API key needed** (GeckoTerminal is keyless).
- `skills/collect-context/` — implemented. `SKILL.md`; `scripts/collect.py` (entrypoint) + `scripts/core/` (`mcp.py` direct MCP client, `context.py` shaping); `config/collect.json`; `references/data-sources.md`. Post-recommend opt-in advisory enrichment (never feeds `safety_score`); same key resolution (`~/.versusos/.env` or env var). Cache output: `skills/collect-context/data/` (gitignored).
- `skills/score/` — implemented (two-phase scoring 0–100 / 0–200). `SKILL.md`; `scripts/score.py` (entrypoint); `scripts/core/` (`mapping.py` vault→DEX-pool join, `scoring.py` two-phase factor computation + ceil2 normalization); `config/scoring.json`; `references/scoring-methodology.md`. Cache output: `skills/score/data/` (gitignored).
- `skills/research-audit/` — implemented (optional, LLM-backed). `SKILL.md`
  (plan→subagents→merge orchestration + rubric); `scripts/plan.py` +
  `scripts/merge.py` (`plan` / `merge` entrypoints) + `scripts/core/`
  (`selection.py`, `verdicts.py`, `llama.py`, `common.py` shared I/O helpers);
  `config/collect.json` (`top_n`, `ttl_days`); `references/` (data-sources +
  0–10 scoring rubric). Cache output: `skills/research-audit/data/` (gitignored).
- `skills/recommend/` — implemented. `SKILL.md` (orchestrator + Pick-bucket gate engine)
  + `references/investment-strategy.md` (expert investment-strategy advisory /
  education overlay — never changes the ranking). Gate-and-disclose Pick buckets
  (Conservative/Balanced/Aggressive) via `scripts/recommend.py` + `config/recommend.json`;
  bucket `score_floor` (80/65/50) and gate signals (`recent_exploit`, `recent_depeg`,
  `dynamic_zero`) drive eligibility disclosure.
- `skills/inspect/` — implemented (inductive token-CA entry). `SKILL.md` +
  `references/data-sources.md`; `scripts/resolve.py` (network-free CLI: token CA
  → matched scored vaults as JSON), `scripts/naming.py` (keyless Dexscreener
  token namer for out-of-coverage), `scripts/core/matching.py` (pure CA→vault
  matching + safety ranking); `config/inspect.json`. Applies an **EVM address
  guard** — non-EVM addresses (Solana/Tron base58 etc.) are rejected up front and
  reported as out of v1 EVM scope. Reads the collect-vault cache
  (`underlyingTokens` index) + `score`'s `vault_scores.json`; **never
  re-scores**. Token-CA centric (v1); advisory/read-only. Reachable as
  `/versusos:inspect`.
- `skills/strategy/` — implemented (doc-only orchestrator, **no script**). `SKILL.md` + `references/backtest-strategy.md` (the executable backtest methodology). Instantiates a self-contained, agent-runnable strategy spec (entry / exit / rebalance rules) from the `score` + `collect-depeg-history` caches into `data/strategy_spec.{md,json}` (gitignored). Advisory/read-only. Reachable as `/versusos:strategy`.
- `tests/` — deterministic unit tests against `tests/fixtures/` (no network), run from repo root; `conftest.py` puts each skill's `scripts/` on `sys.path` (collect-vault first, so `import collect` resolves to it; other entrypoints load via importlib aliases).

## Conventions

- Keep deterministic scoring/ranking pure and testable; all tunable constants live in
  the owning skill's `config/` (JSON), not in code.
- The plugin is dependency-free (Python stdlib only) — do not add third-party imports
  to any skill's `scripts/`.
- Keep each `SKILL.md` concise — push detail into that skill's `references/`
  (progressive disclosure). Reference bundled files with `./` relative paths.
- External data is fetched once and cached to JSON under the collecting skill's
  `data/`; scoring reads cache, never the network.
- Any future stub skill must say "not implemented yet — tell the user and stop";
  never fabricate data, scores, or rankings.

## Extending

Growth is additive — no restructure needed:

- **More skills** — add a sibling self-contained `skills/<name>/` folder
  (SKILL.md + its own scripts/config/references). It becomes `/versusos:<name>`.
  Follow the shared SKILL.md orchestration pattern: a Pipeline section, an
  Announce-at-start line, and a Next-stage handoff in Presenting results.
  User-facing lines speak value, not internals (no skill/engine/stage names; see
  `skills/recommend/SKILL.md` → **User-facing language**), and sub-skills stay
  silent when orchestrated by a parent pipeline.
- **Slash commands** — add `commands/<name>.md`; each becomes a user-typed `/<name>`.
- **Hooks** — add `hooks/hooks.json` for event hooks (e.g. SessionStart).
- **Subagents** — add `agents/<name>.md`.

When publishing changes, bump `version` in `.claude-plugin/plugin.json` and the matching
entry in `.claude-plugin/marketplace.json` (keep them in sync).

## External Data Sources

DeFiLlama Yields (vault APY/TVL) + the **CoinMarketCap AI Agent Hub** — the v4
DEX REST API (`quotes/latest`, batched per chain) for pool snapshots (liquidity,
price) and the CMC MCP server for qualitative context (called directly by the
collector script — no MCP registration). Both read the key from `~/.versusos/.env`
(dotenv, `CMC_PRO_API_KEY=<key>`) or the `CMC_PRO_API_KEY` env var (override).
Pool discovery uses the Dexscreener `token-pairs/v1` endpoint (keyless) to find
all USDC/USDT-paired pools for each vault's underlying token; Dexscreener also
supplies per-side pooled amounts and serves as the snapshot fallback when CMC does
not index a pool. CMC `spot-pairs/latest` cannot discover pools by token address
(verified). **GeckoTerminal** (keyless) supplies 180-day daily and 12-hour minute
OHLCV — fetched by `collect-depeg-history` (opt-in) for the top-N scored vaults
only; peg classification is derived downstream.
DeFiLlama also serves the free hacks catalog and per-protocol `audits` code,
joined per protocol in collect-vault as the `exploits` and `audit_triage` blocks;
the optional `research-audit` skill layers LLM web research on top to verify and
grade audits (0–10, cited) — **advisory-only, never enters `safety_score`**. See
`skills/collect-vault/references/data-sources.md`,
`skills/collect-dex/references/data-sources.md`,
`skills/collect-depeg-history/references/data-sources.md`, and
`skills/research-audit/references/`.
