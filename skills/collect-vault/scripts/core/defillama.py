"""DeFiLlama Yields network client.

Public, key-less HTTP via the standard library (urllib) — no third-party
dependencies, so the skill folder runs as-is with no install. Kept thin: fetch the
yield vaults and shape into plain Python; all filtering lives in filters.py so it
can be tested without the network.
"""
from __future__ import annotations

import json
import time
import urllib.request

POOLS_URL = "https://yields.llama.fi/pools"
HACKS_URL = "https://api.llama.fi/hacks"
PROTOCOLS_URL = "https://api.llama.fi/protocols"


def _get_json(url: str, *, urlopen=None, timeout: float = 30.0,
              retries: int = 3, backoff: float = 1.0):
    """GET ``url`` and return parsed JSON, retrying with exponential backoff.

    ``urlopen`` defaults to ``urllib.request.urlopen``; tests pass a fake callable
    returning a context manager whose ``.read()`` yields JSON bytes.
    """
    opener = urlopen or urllib.request.urlopen
    last_error = None
    for attempt in range(retries):
        try:
            with opener(url, timeout=timeout) as response:
                return json.loads(response.read())
        except Exception as error:  # network / HTTP / JSON parse
            last_error = error
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_error}")


def fetch_vaults(*, urlopen=None) -> list[dict]:
    """Return the full list of yield vaults (DeFiLlama "pools") as raw dicts."""
    payload = _get_json(POOLS_URL, urlopen=urlopen)
    return payload.get("data", [])


def fetch_hacks(*, urlopen=None) -> list[dict]:
    """Return DeFiLlama's hack catalog (``/hacks`` returns a top-level list)."""
    payload = _get_json(HACKS_URL, urlopen=urlopen)
    return payload if isinstance(payload, list) else []


def fetch_protocols(*, urlopen=None) -> list[dict]:
    """Return the DeFiLlama protocol list (``/protocols`` returns a top-level list)."""
    payload = _get_json(PROTOCOLS_URL, urlopen=urlopen)
    return payload if isinstance(payload, list) else []


if __name__ == "__main__":
    raise SystemExit(
        "defillama.py is the DeFiLlama HTTP client imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )
