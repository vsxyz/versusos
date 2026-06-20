"""Pure, network-free filtering and sorting for DeFiLlama yield vaults.

Operates on raw vault dicts as returned by the DeFiLlama /pools API (DeFiLlama
calls these "pools") so no fields are lost. Consumed by collect.py after fetching.

Filter rule: only single-token vaults pass, and only when the token is in the
allowed set (USD stables); two-token pairs and vaults with three or more tokens
are excluded.
"""
from __future__ import annotations


def vault_token_symbols(vault: dict) -> list[str]:
    """Split a vault's ``symbol`` into upper-cased component token symbols.

    "USDC-USDT" -> ["USDC", "USDT"];  "USDC" -> ["USDC"];  "" / missing -> [].
    """
    symbol = vault.get("symbol") or ""
    return [part.strip().upper() for part in symbol.split("-") if part.strip()]


def build_allowed_symbols(token_config: dict, usd_stable_symbols: set[str]) -> set[str]:
    """Expand configured token groups + explicit symbols into one allowed set.

    Supported groups: ``ALL_USD_STABLES`` (expands to ``usd_stable_symbols``).
    All symbols are upper-cased.
    """
    allowed: set[str] = set()
    for group in token_config.get("groups") or []:
        if group == "ALL_USD_STABLES":
            allowed |= {symbol.upper() for symbol in usd_stable_symbols}
    for symbol in token_config.get("symbols") or []:
        allowed.add(symbol.upper())
    return allowed


def passes_chain(vault: dict, filter_config: dict) -> bool:
    """True unless ``evm_only`` is set and the vault's chain is denylisted.

    Denylist (not allowlist) so a newly added EVM chain is never wrongly dropped;
    only known non-EVM families in ``non_evm_chains`` are excluded. Case-insensitive.
    """
    if not filter_config.get("evm_only"):
        return True
    denylist = {c.lower() for c in filter_config.get("non_evm_chains") or []}
    return (vault.get("chain") or "").strip().lower() not in denylist


def passes_filters(vault: dict, filter_config: dict, allowed: set[str]) -> bool:
    """Only single-token allowed-USD-stable vaults on an in-scope chain pass."""
    tokens = vault_token_symbols(vault)
    if len(tokens) != 1 or tokens[0] not in allowed:
        return False
    if not passes_chain(vault, filter_config):
        return False
    min_tvl = filter_config.get("min_tvl_usd")
    if min_tvl is not None and (vault.get("tvlUsd") or 0) < min_tvl:
        return False
    return True


def filter_vaults(vaults: list[dict], filter_config: dict, allowed: set[str]) -> list[dict]:
    """Return the vaults that pass all configured filters (input order kept)."""
    return [vault for vault in vaults if passes_filters(vault, filter_config, allowed)]


def sort_vaults(vaults: list[dict], by: str, desc: bool) -> list[dict]:
    """Sort vaults by a field. Vaults missing the field sort last either way."""
    present = [vault for vault in vaults if vault.get(by) is not None]
    missing = [vault for vault in vaults if vault.get(by) is None]
    present.sort(key=lambda vault: vault.get(by), reverse=desc)
    return present + missing


if __name__ == "__main__":
    raise SystemExit(
        "filters.py provides pure filter/sort helpers imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )
