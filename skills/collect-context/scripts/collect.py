"""Collect qualitative market context via the CMC MCP server -> JSON cache.

Speaks MCP directly (core/mcp.py) — no MCP client registration needed; the
only prerequisite is the CMC key, read from ~/.versusos/.env
(CMC_PRO_API_KEY=<key>) or the CMC_PRO_API_KEY env var. Coins come from
the collect-vault cache (vaults[].symbol). Partial failures warn and keep
going; the cache is written whenever anything was collected.
Run from this skill folder (no install needed):
    python scripts/collect.py [--mapping ../collect-vault/data/defillama_yields.json]
                              [--config config/collect.json]
                              [--out data/context.json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time

from core import context, mcp

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = str(SKILL_ROOT.parent / "collect-vault" / "data"
                      / "defillama_yields.json")
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "collect.json")
DEFAULT_OUT = str(SKILL_ROOT / "data" / "context.json")

ENV_KEY = "CMC_PRO_API_KEY"
KEY_FILE = pathlib.Path.home() / ".versusos" / ".env"


def resolve_api_key() -> str | None:
    """CMC_PRO_API_KEY from the environment, else from ~/.versusos/.env.

    The key file is dotenv-style: KEY=VALUE lines, # comments and blank
    lines ignored, optional surrounding quotes stripped. Module-global
    KEY_FILE is read at call time so tests can monkeypatch it.
    """
    value = os.environ.get(ENV_KEY)
    if value:
        return value
    try:
        lines = KEY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip() == ENV_KEY:
            return value.strip().strip("'\"") or None
    return None


def load_json(path: str) -> dict:
    """Load a JSON config file into a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def write_cache(payload: dict, out_path: str) -> None:
    """Write the payload to out_path as pretty JSON, creating parent dirs."""
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def mapping_symbols(mapping: dict, whitelist=None, extra=None) -> list[str]:
    """Unique stablecoin token symbols from the collect-vault cache.

    Splits each vault's ``symbol`` into component tokens (LP pairs like
    "USDC-USDT" -> USDC, USDT), upper-cased and de-duplicated in first-seen
    order, so each resolves to a single CMC coin for news lookup.

    ``whitelist`` (case-insensitive) restricts the result to recognised
    stablecoins, dropping pair vaults' non-stable partners (WETH, ZEC, …) and
    protocol-wrapped vault-token noise; pass ``None`` to keep every symbol.
    ``extra`` symbols are always appended (even if absent from the vaults or
    excluded by the whitelist), so the user can research any coin on request.
    """
    allow = {s.strip().upper() for s in (whitelist or []) if s and s.strip()}
    symbols = []
    for vault in mapping.get("vaults") or []:
        for part in (vault.get("symbol") or "").split("-"):
            part = part.strip().upper()
            if not part or (allow and part not in allow):
                continue
            symbols.append(part)
    for part in (extra or []):
        part = part.strip().upper()
        if part:
            symbols.append(part)
    return list(dict.fromkeys(symbols))


def collect_coin_news(symbols: list[str], options: dict, api_key: str, *,
                      call_tool=None, sleep=time.sleep) -> list[dict]:
    """Resolve each symbol to a CMC id and fetch its news; failures warn.

    An unresolved or failed coin still appears in the output with empty news
    so downstream consumers see the full coin list.
    """
    call = call_tool or mcp.call_tool
    coins = []
    for index, symbol in enumerate(symbols):
        if index:
            sleep(options["throttle_seconds"])
        news = []
        try:
            search = call("search_cryptos", {"query": symbol, "limit": 5},
                          api_key=api_key)
            coin_id = context.resolve_id(search, symbol)
            if coin_id is None:
                print(f"WARNING: {symbol} did not resolve to a CMC id; "
                      "news skipped.", file=sys.stderr)
            else:
                payload = call("get_crypto_latest_news",
                               {"id": coin_id, "limit": options["news_limit"]},
                               api_key=api_key)
                news = context.shape_news(payload)
        except RuntimeError as error:
            print(f"WARNING: news collection failed for {symbol}: {error}",
                  file=sys.stderr)
        coins.append({"symbol": symbol, "news": news})
    return coins


def fetch_fear_greed(api_key: str, *, call_tool=None) -> dict | None:
    """Fear & Greed from global metrics; a failure warns and yields None."""
    call = call_tool or mcp.call_tool
    try:
        return context.extract_fear_greed(
            call("get_global_metrics_latest", {}, api_key=api_key))
    except RuntimeError as error:
        print(f"WARNING: global metrics fetch failed: {error}",
              file=sys.stderr)
        return None


def fetch_narratives(api_key: str, *, call_tool=None) -> list[dict]:
    """Trending narratives; a failure warns and yields []."""
    call = call_tool or mcp.call_tool
    try:
        return context.shape_narratives(
            call("trending_crypto_narratives", {}, api_key=api_key))
    except RuntimeError as error:
        print(f"WARNING: narratives fetch failed: {error}", file=sys.stderr)
        return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect qualitative market context for stablecoins.")
    parser.add_argument("--mapping", default=DEFAULT_MAPPING)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument(
        "--extra-symbols", default="",
        help="comma-separated coin symbols to research in addition to the "
             "stablecoin whitelist, e.g. --extra-symbols ETH,BTC")
    parser.add_argument(
        "--all-symbols", action="store_true",
        help="bypass the stablecoin whitelist and research every vault symbol")
    args = parser.parse_args(argv)

    api_key = resolve_api_key()
    if not api_key:
        print("ERROR: no CMC API key found. Create ~/.versusos/.env containing "
              "the line CMC_PRO_API_KEY=<your key> (free signup at "
              "https://pro.coinmarketcap.com), or export CMC_PRO_API_KEY.",
              file=sys.stderr)
        return 1

    options = load_json(args.config)
    whitelist = None if args.all_symbols else (
        options.get("stablecoin_whitelist") or None)
    extra = [s for s in args.extra_symbols.split(",") if s.strip()]
    symbols = mapping_symbols(load_json(args.mapping),
                              whitelist=whitelist, extra=extra)
    coins = collect_coin_news(symbols, options, api_key)
    fear_greed = fetch_fear_greed(api_key)
    narratives = fetch_narratives(api_key)

    news_total = sum(len(coin["news"]) for coin in coins)
    if news_total == 0 and fear_greed is None and not narratives:
        print("ERROR: nothing collected; cache not written "
              "(existing cache preserved).", file=sys.stderr)
        return 1

    payload = {
        "source": "coinmarketcap-mcp",
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "fear_greed": fear_greed,
        "stablecoins": coins,
        "narratives": narratives,
    }
    write_cache(payload, args.out)
    print(f"News {news_total} across {len(coins)} coins, "
          f"fear&greed {'ok' if fear_greed else 'missing'}, "
          f"narratives {len(narratives)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
