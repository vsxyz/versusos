"""Shared HTTP helper for the collect-dex API clients.

Every request sends a custom User-Agent (Dexscreener rejects the default
``Python-urllib`` one with HTTP 403); clients add their own headers on top
(e.g. the CMC API key). Transient network/parse errors retry with exponential
backoff; HTTP 429 has a separate, Retry-After-aware retry budget so a rate
limit clears its window instead of failing fast (see ``get_json``).
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "http.py provides the shared GET helper imported by the collect-dex "
        "clients — it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )

import datetime
import email.utils
import json
import time
import urllib.error
import urllib.request

USER_AGENT = "versusos-collect-dex/1.0"


def _retry_after_seconds(error, default, cap):
    """Seconds to wait after a 429, read from its ``Retry-After`` header.

    Accepts the delta-seconds form (``"7"``) or the HTTP-date form; falls back
    to ``default`` when the header is absent or unparseable, and never returns
    more than ``cap`` so a hostile or huge value cannot stall the run.
    """
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


def get_json(url: str, *, headers: dict | None = None, urlopen=None,
             timeout: float = 30.0, retries: int = 3, backoff: float = 1.0,
             rate_limit_retries: int = 5, rate_limit_backoff: float = 5.0,
             rate_limit_cap: float = 60.0):
    """GET ``url`` and return parsed JSON, retrying transient errors and 429s.

    ``retries`` is the total number of attempts for transient failures
    (network errors, non-429 HTTP errors, JSON parse), spaced by
    ``backoff * 2**n``. HTTP 429 (rate limit) is handled on a *separate*
    budget: up to ``rate_limit_retries`` waits that honour the response's
    ``Retry-After`` header (or, absent it, ``rate_limit_backoff * 2**n``), each
    clamped to ``rate_limit_cap`` seconds. Keeping the budgets independent means
    a rate limit never burns the transient-error retries, and the wait is long
    enough to clear the limit window (a blind 1-2s retry never does).

    ``urlopen`` defaults to ``urllib.request.urlopen``; tests pass a fake callable
    that receives the built Request and returns a context manager whose
    ``.read()`` yields JSON bytes.
    """
    # Mirrors collect-vault's defillama._get_json but is kept separate so each
    # skill stays self-contained; unlike there, the opener here receives a
    # urllib.request.Request (not a URL string) to carry the custom User-Agent.
    opener = urlopen or urllib.request.urlopen
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    last_error = None
    attempt = 0     # transient-error budget (network / non-429 HTTP / parse)
    rate_hits = 0   # independent 429 budget
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
        f"({rate_hits} rate-limited): {last_error}"
    ) from last_error
