# Data Sources — collect-context

One source: the **CoinMarketCap MCP server** (the CMC AI Agent Hub's
real-time tool layer), called directly by the collector script.

## CMC MCP server — direct JSON-RPC over HTTP

- **Endpoint:** `POST https://mcp.coinmarketcap.com/mcp` (streamable HTTP).
- **Auth:** header `X-CMC-MCP-API-KEY` carrying the same CMC key as
  collect-dex, resolved at runtime from the `CMC_PRO_API_KEY` env var or the
  dotenv key file `~/.versusos/.env` (`CMC_PRO_API_KEY=<key>`; free signup at
  https://pro.coinmarketcap.com). Never commit the key.
- **Protocol (live-verified 2026-06-11):** the server is stateless for tool
  calls — a bare `tools/call` POST works without an `initialize` handshake or
  `Mcp-Session-Id`. Responses are `application/json` JSON-RPC envelopes; the
  tool payload is a JSON string at `result.content[0].text`, and tool-level
  failures set `result.isError` with the message in the text. This is why no
  MCP client registration (`claude mcp add`) is needed — `core/mcp.py` is a
  ~60-line stdlib client.

## Tools used (of the server's 12)

| Tool | Arguments | Returns (shape) |
|---|---|---|
| `search_cryptos` | `{query, limit≤5}` | **shape-unstable** (live-verified 2026-06-16): a single match returns a plain list `[{id, name, symbol, slug, rank}]`; multiple matches return a `{headers, rows}` table with the same columns. `core/context.py` normalises both — symbol→CMC id resolution (exact, case-insensitive match) |
| `get_crypto_latest_news` | `{id (required, string), limit≤20}` | `{headers, rows}` table: `title, description, content, url, publishedAt, quality` |
| `get_global_metrics_latest` | `{}` | object; Fear & Greed at `sentiment.fear_greed.current` = `{value: "<classification>", index: <0-100>}` |
| `trending_crypto_narratives` | `{}` | `{categoryList: {headers, rows}}`: `trendingRank, slug, categoryCmcUrl, categoryName, …` |

## Caveats

- The news tool requires the **CMC numeric id** (e.g. USDC = 3408), not a
  symbol — hence the `search_cryptos` resolution step.
- News/narrative tables are header/row arrays, not objects —
  `core/context.py` zips them; cells can be missing.
- Each `tools/call` is assumed to cost API credits like a REST call (not
  directly verified — MCP responses carry no `credit_count`); the collector
  throttles politely (`throttle_seconds`).
- The four tool names are hardcoded in the collector. If the server renames
  or removes one, that call fails and degrades per the skill's
  partial-failure rule (warn + partial cache) — re-check `tools/list` and
  update `scripts/collect.py` if warnings start appearing.

## Rejected alternatives (and why)

- **User-registered MCP server** (`claude mcp add` + SKILL.md-driven calls):
  works, but forces per-user setup beyond the API key — rejected as a UX
  requirement.
- **Plugin-bundled `.mcp.json`:** `${ENV}` does not expand inside plugin MCP
  configs (claude-code issue #9427, closed not-planned), and a hardcoded key
  cannot ship in a public repo.
- **REST equivalents:** `/v3/fear-and-greed/latest` works, but the news
  endpoint `/v1/content/latest` is plan-gated (HTTP 403, code 1006) on the
  current plan.
