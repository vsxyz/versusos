"""Pure, network-free vault -> DEX-pool join for the score skill.

Maps each collect-vault vault record to its associated collect-dex pool records
(1:N). The join keys: each of the vault's component token symbols must match a
``stablecoins[].symbol`` entry, and the pool's chain must match the vault's
chain case-insensitively (vault "Ethereum" vs dex "ethereum").

``vault_token_symbols`` intentionally duplicates the tiny split helper from
collect-vault's filters.py — skills are self-contained and never import from
each other.
"""
from __future__ import annotations


def vault_token_symbols(vault: dict) -> list[str]:
    """Split a vault's ``symbol`` into upper-cased component token symbols."""
    symbol = (vault.get("symbol") or "").strip()
    if not symbol:
        return []
    return [part.upper() for part in symbol.split("-") if part]


def build_pool_index(dex_payload: dict | None) -> dict[str, list[dict]]:
    """Index a collect-dex cache payload as {SYMBOL: [pool, ...]}.

    Returns an empty index when the payload is absent (collect-dex cache
    missing) — every vault then matches zero pools.
    """
    if not dex_payload:
        return {}
    index: dict[str, list[dict]] = {}
    for entry in dex_payload.get("stablecoins", []):
        symbol = (entry.get("symbol") or "").strip().upper()
        if symbol:
            index.setdefault(symbol, []).extend(entry.get("pools", []))
    return index


def match_pools(vault: dict, pool_index: dict[str, list[dict]]) -> list[dict]:
    """Return the vault's associated pools: union over its token symbols,
    restricted to pools on the vault's chain (case-insensitive)."""
    chain = (vault.get("chain") or "").lower()
    return [
        pool
        for symbol in vault_token_symbols(vault)
        for pool in pool_index.get(symbol, [])
        if (pool.get("chain") or "").lower() == chain
    ]


def match_pools_by_target(vault: dict, pool_index: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Group the vault's matched pools by target token symbol.

    Like ``match_pools`` but keyed by the matched target symbol (a vault component
    symbol present in the DEX index), restricted to the vault's chain
    (case-insensitive). The score skill computes DEX factors per target and takes
    the minimum.
    """
    chain = (vault.get("chain") or "").lower()
    grouped: dict[str, list[dict]] = {}
    for symbol in vault_token_symbols(vault):
        pools = [pool for pool in pool_index.get(symbol, [])
                 if (pool.get("chain") or "").lower() == chain]
        if pools:
            grouped[symbol] = pools
    return grouped


def merge_history(pool_index: dict[str, list[dict]],
                  history_payload: dict | None) -> dict[str, list[dict]]:
    """Fill ohlcv_daily/ohlcv_minute on indexed pools from collect-depeg-history.

    ``history_payload`` is the ohlcv_history.json cache (``by_pool`` keyed by
    "<chain>|<pool_address>|<token_address>"). Mutates the pool dicts in place
    (they are shared with the dex payload), so the scorer reads the OHLCV via the
    same ``pool["ohlcv_daily"]`` access as before. Absent entry -> pool untouched.
    """
    by_pool = (history_payload or {}).get("by_pool") or {}
    for pools in pool_index.values():
        for pool in pools:
            key = (f'{pool.get("chain")}|{pool.get("pool_address")}'
                   f'|{pool.get("token_address")}')
            entry = by_pool.get(key)
            if entry:
                pool["ohlcv_daily"] = entry.get("ohlcv_daily")
                pool["ohlcv_minute"] = entry.get("ohlcv_minute")
    return pool_index


if __name__ == "__main__":
    raise SystemExit(
        "mapping.py provides the pure vault->DEX-pool join imported by score.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the scorer instead:  python scripts/score.py"
    )
