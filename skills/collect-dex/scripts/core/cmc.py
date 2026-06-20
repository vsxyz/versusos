"""CoinMarketCap v4 DEX API client: batched pair snapshots.

The data layer of the CMC AI Agent Hub (REST path). Auth is the
``X-CMC_PRO_API_KEY`` header; quotes cost 1 credit per pair. Only the quotes
endpoint is used: per-side pooled amounts are not served (Dexscreener fills
them) and the OHLCV endpoints returned persistent 500s on the current plan
as of 2026-06-11 (GeckoTerminal keeps serving history). Shaping lives in
``dexpools`` — this module only fetches and keys responses.
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "cmc.py is the CoinMarketCap snapshot client imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )

import re
import urllib.parse

from core import http

QUOTES_URL = "https://pro-api.coinmarketcap.com/v4/dex/pairs/quotes/latest"
AUX = "holders,security_scan,buy_tax,sell_tax"

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_contract_address(value: str | None) -> bool:
    """True only for a plain EVM contract address (``0x`` + 40 hex).

    Dexscreener's ``pairAddress`` is sometimes a 32-byte pool id (``0x`` + 64
    hex, e.g. Uniswap v4) or a hyphen-joined Curve/registry composite. CMC's
    ``contract_address`` param rejects those with HTTP 400, so callers exclude
    them from the CMC request (the Dexscreener snapshot still covers the pool).
    """
    return bool(value and _ADDRESS_RE.match(value))


def fetch_pairs(network: str, pool_addresses: list[str], *, api_key: str,
                urlopen=None) -> dict[str, dict]:
    """Fetch snapshots for pools on one network, keyed by lowercase address.

    One batched call per network (comma-joined addresses; ``skip_invalid``
    keeps one bad address from failing the batch). Empty ``pool_addresses``
    returns ``{}`` without making a network call.
    """
    if not pool_addresses:
        return {}
    query = urllib.parse.urlencode({
        "network_slug": network,
        "contract_address": ",".join(pool_addresses),
        "aux": AUX,
        "skip_invalid": "true",
    })
    payload = http.get_json(QUOTES_URL + "?" + query,
                            headers={"X-CMC_PRO_API_KEY": api_key},
                            urlopen=urlopen)
    pairs = payload.get("data") or []
    return {pair["contract_address"].lower(): pair
            for pair in pairs if pair.get("contract_address")}
