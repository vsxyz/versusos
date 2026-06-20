"""Pure, network-free shaping for CMC MCP tool payloads.

The news and narratives tools return header/row tables; this module turns
them (plus the global-metrics object) into the context cache schema. No
network and no I/O, so everything here is testable against tests/fixtures/.
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "context.py provides pure shaping helpers imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )


def _table_rows(payload: dict) -> list[dict]:
    """{headers, rows} table -> list of row dicts (missing cells -> absent)."""
    headers = (payload or {}).get("headers") or []
    rows = (payload or {}).get("rows") or []
    return [dict(zip(headers, row)) for row in rows if isinstance(row, list)]


def _search_rows(payload) -> list[dict]:
    """Normalise a search_cryptos payload to a list of row dicts.

    ``search_cryptos`` is shape-unstable (live-verified 2026-06-16): a single
    match comes back as a plain list of objects ``[{id, symbol, …}]`` while
    multiple matches come back as a ``{headers, rows}`` columnar table (like
    the news/narratives tools). Accept both.
    """
    if isinstance(payload, dict):
        return _table_rows(payload)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def resolve_id(search_payload, symbol: str) -> str | None:
    """Pick the CMC id whose symbol matches exactly (case-insensitive)."""
    wanted = (symbol or "").lower()
    for row in _search_rows(search_payload):
        if (row.get("symbol") or "").lower() == wanted:
            return str(row["id"])
    return None


def shape_news(payload: dict) -> list[dict]:
    """News table -> [{title, date, url}], dropping items without a URL."""
    items = []
    for row in _table_rows(payload):
        if not row.get("url"):
            continue  # citation basis is mandatory — drop, never invent
        items.append({
            "title": row.get("title"),
            "date": row.get("publishedAt"),
            "url": row["url"],
        })
    return items


def extract_fear_greed(metrics_payload: dict) -> dict | None:
    """Global metrics -> {value: <0-100 int>, classification: <str>} or None.

    CMC nests it at sentiment.fear_greed.current where ``index`` is the
    number and ``value`` the classification text.
    """
    current = (((metrics_payload or {}).get("sentiment") or {})
               .get("fear_greed") or {}).get("current") or {}
    if current.get("index") is None:
        return None
    return {"value": current["index"], "classification": current.get("value")}


def shape_narratives(payload: dict) -> list[dict]:
    """categoryList table -> [{rank, name, url}], in trending order."""
    rows = _table_rows((payload or {}).get("categoryList") or {})
    return [{"rank": row.get("trendingRank"),
             "name": row.get("categoryName"),
             "url": row.get("categoryCmcUrl")}
            for row in rows if row.get("categoryName")]
