"""Pure, network-free selection of which pools to deep-collect history for.

Given the score skill's ranked vaults and the collect-dex cache, returns the
history_selected pools belonging to the top-N vaults' target symbols (on each
vault's chain), deduplicated. No network and no I/O — testable in isolation.
"""
from __future__ import annotations


def _symbols(symbol):
    """A score record's ``symbol`` -> upper-cased component token symbols."""
    text = (symbol or "").strip()
    return [part.upper() for part in text.split("-") if part] if text else []


def select_targets(scores, dex_payload, top_n):
    """Pools to fetch OHLCV for: history_selected pools of the top-N vaults.

    Each returned item is {chain, pool_address, token_address, gecko_network,
    symbol}. Deduped by (chain, pool_address, token_address), in vault-rank order.
    """
    selected_by_symbol: dict[str, list[dict]] = {}
    for entry in (dex_payload or {}).get("stablecoins", []):
        symbol = (entry.get("symbol") or "").strip().upper()
        for pool in entry.get("pools", []):
            if (pool.get("flags") or {}).get("history_selected"):
                selected_by_symbol.setdefault(symbol, []).append(pool)
    seen: set[tuple] = set()
    out: list[dict] = []
    for record in (scores or [])[:top_n]:
        chain = (record.get("chain") or "").lower()
        for symbol in _symbols(record.get("symbol")):
            for pool in selected_by_symbol.get(symbol, []):
                if (pool.get("chain") or "").lower() != chain:
                    continue
                key = (pool["chain"], pool["pool_address"], pool["token_address"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "chain": pool["chain"],
                    "pool_address": pool["pool_address"],
                    "token_address": pool["token_address"],
                    "gecko_network": pool.get("gecko_network"),
                    "symbol": symbol,
                })
    return out


if __name__ == "__main__":
    raise SystemExit(
        "targets.py provides the pure top-N pool selection imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py")
