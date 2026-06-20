"""Dexscreener network client: per-token pool discovery.

Free public API, no key. ``fetch_token_pools`` lists every pool containing a
token (token-pairs/v1) — the discovery primitive and the source of per-side
pooled amounts CMC's quotes endpoint does not serve. Unindexed tokens return an
empty list. Responses carry checksummed addresses; callers lowercase them.
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "dexscreener.py is the snapshot client imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )

from core import http

TOKEN_PAIRS_URL = "https://api.dexscreener.com/token-pairs/v1/{chain}/{token}"


def fetch_token_pools(chain: str, token_address: str, *, urlopen=None) -> list[dict]:
    """All pools containing ``token_address`` on ``chain`` (token-pairs/v1).

    Returns the raw pair list (the endpoint responds with a bare JSON array);
    a non-list response -> ``[]``. Empty ``token_address`` -> ``[]`` without a
    network call. Pair objects carry ``baseToken``/``quoteToken`` with
    address+symbol, ``priceUsd``, ``priceNative``,
    ``liquidity.{usd,base,quote}``, ``volume.h24``, ``pairAddress``, ``dexId``.
    """
    if not token_address:
        return []
    url = TOKEN_PAIRS_URL.format(chain=chain, token=token_address)
    payload = http.get_json(url, urlopen=urlopen)
    return payload if isinstance(payload, list) else []
