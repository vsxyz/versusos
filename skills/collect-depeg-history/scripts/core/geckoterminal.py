"""GeckoTerminal OHLCV client (daily depeg + minute dynamic) for collect-depeg-history.

Free public API, no key — 30 calls/min keyless (raised from 10 on 2023-04-19).
The caller throttles before every call; HTTP 429 is retried here on a separate,
Retry-After-aware budget whose fallback backoff is sized to the 60-second rate
window (no Retry-After header is documented), so a rate limit waits out its window
and clears silently instead of failing fast. The public window is capped at 180
days. The ``token`` query param orients candles to the target token's price
regardless of base/quote order. Self-contained: the GET helper is inlined (this
skill has a single HTTP client), so it imports nothing from sibling skills.
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "geckoterminal.py is the OHLCV client imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py")

import datetime
import email.utils
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "versusos-collect-depeg-history/1.0"
OHLCV_URL = ("https://api.geckoterminal.com/api/v2/networks/{network}"
             "/pools/{address}/ohlcv/day")
MINUTE_OHLCV_URL = ("https://api.geckoterminal.com/api/v2/networks/{network}"
                    "/pools/{address}/ohlcv/minute")

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_contract_address(value: str | None) -> bool:
    """True only for a plain EVM contract address (``0x`` + 40 hex).

    GeckoTerminal's pool endpoint addresses a pool by its contract address;
    Dexscreener's ``pairAddress`` is sometimes a 32-byte pool id (``0x`` + 64
    hex, e.g. Uniswap v4) or a hyphen-joined Curve/registry composite, which 404
    there. Callers skip those targets. Duplicated from collect-dex's cmc.py —
    skills are self-contained and never import from each other.
    """
    return bool(value and _ADDRESS_RE.match(value))


def _retry_after_seconds(error, default, cap):
    """Seconds to wait after a 429, read from its Retry-After header (delta or
    HTTP-date); falls back to ``default`` when absent/unparseable, capped at ``cap``."""
    header = error.headers.get("Retry-After") if error.headers else None
    wait = default
    if header:
        header = header.strip()
        if header.isdigit():
            wait = float(header)
        else:
            try:
                when = email.utils.parsedate_to_datetime(header)
                now = datetime.datetime.now(datetime.timezone.utc)
                wait = max(0.0, (when - now).total_seconds())
            except (TypeError, ValueError):
                wait = default
    return min(wait, cap)


def get_json(url, *, urlopen=None, timeout=30.0, retries=3, backoff=1.0,
             rate_limit_retries=5, rate_limit_backoff=15.0, rate_limit_cap=60.0):
    """GET ``url`` -> parsed JSON, retrying transient errors and 429s on
    independent budgets (429 honours Retry-After). See module docstring."""
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None
    attempt = 0
    rate_hits = 0
    while True:
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 429:
                rate_hits += 1
                if rate_hits > rate_limit_retries:
                    break
                default = rate_limit_backoff * (2 ** (rate_hits - 1))
                time.sleep(_retry_after_seconds(error, default, rate_limit_cap))
                continue
            attempt += 1
            if attempt < retries:
                time.sleep(backoff * (2 ** (attempt - 1)))
                continue
            break
        except Exception as error:  # network / JSON parse
            last_error = error
            attempt += 1
            if attempt < retries:
                time.sleep(backoff * (2 ** (attempt - 1)))
                continue
            break
    raise RuntimeError(
        f"GET {url} failed after {attempt + rate_hits} attempts "
        f"({rate_hits} rate-limited): {last_error}") from last_error


def _fetch(url_template, network, pool_address, *, limit, token_address, urlopen,
           **kwargs):
    query = urllib.parse.urlencode({
        "aggregate": 1, "limit": limit, "currency": "usd", "token": token_address})
    url = url_template.format(network=network, address=pool_address) + "?" + query
    payload = get_json(url, urlopen=urlopen, **kwargs)
    attributes = (payload.get("data") or {}).get("attributes") or {}
    return attributes.get("ohlcv_list") or []


def fetch_daily_ohlcv(network, pool_address, *, days, token_address, urlopen=None,
                      **kwargs):
    """Up to ``days`` daily candles, newest first: [epoch_s, o, h, l, c, vol_usd]."""
    return _fetch(OHLCV_URL, network, pool_address, limit=days,
                  token_address=token_address, urlopen=urlopen, **kwargs)


def fetch_minute_ohlcv(network, pool_address, *, minutes, token_address, urlopen=None,
                       **kwargs):
    """Up to ``minutes`` 1-minute candles, newest first (12h window = 720 fits one call)."""
    return _fetch(MINUTE_OHLCV_URL, network, pool_address, limit=minutes,
                  token_address=token_address, urlopen=urlopen, **kwargs)
