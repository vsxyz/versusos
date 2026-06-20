"""DeFiLlama per-protocol client for research-audit (audit_links seed only).

`GET /protocol/{slug}` exposes ``audit_links`` (report URLs) that the bulk
``/protocols`` endpoint omits. Used purely as a research seed for the LLM, so it
is **best-effort**: any failure returns ``[]`` and research proceeds without it.
stdlib urllib only; ``urlopen`` is injectable for tests.
"""
from __future__ import annotations

import json
import urllib.request

PROTOCOL_URL = "https://api.llama.fi/protocol/{slug}"


def fetch_audit_links(slug: str, *, urlopen=None, timeout: float = 30.0) -> list:
    """Return ``audit_links`` for a protocol slug, or ``[]`` on any failure."""
    opener = urlopen or urllib.request.urlopen
    try:
        with opener(PROTOCOL_URL.format(slug=slug), timeout=timeout) as response:
            payload = json.loads(response.read())
    except Exception:  # network / HTTP / JSON parse — seed is optional
        return []
    links = payload.get("audit_links") if isinstance(payload, dict) else None
    return links or []


if __name__ == "__main__":
    raise SystemExit(
        "llama.py provides the audit_links client imported by plan.py — "
        "it is not a standalone entrypoint.\nRun:  python scripts/plan.py"
    )
