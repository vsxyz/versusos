"""Pure, network-free pool discovery for collect-dex.

Seeds target tokens from the collect-vault cache (``underlyingTokens``), turns
Dexscreener token-pairs responses into per-pool collection jobs (keeping only
USDC/USDT-paired pools), and selects the single most-liquid price-sane,
GeckoTerminal-fetchable pool per target for history collection. No network and
no I/O, so everything here is testable against tests/fixtures/.
"""
from __future__ import annotations

import re

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_contract_address(value: str | None) -> bool:
    """True only for a plain EVM contract address (``0x`` + 40 hex).

    Dexscreener's ``pairAddress`` is sometimes a 32-byte pool id (``0x`` + 64
    hex, Uniswap v4) or a hyphen-joined Curve/registry composite; GeckoTerminal
    404s on those, so the per-target history pool must be a plain contract
    address. Kept local (mirrors cmc.py's copy) so this pure, network-free
    module need not import the cmc client.
    """
    return bool(value and _ADDRESS_RE.match(value))


def vault_targets(vault_payload: dict, chain_aliases: dict,
                  gecko_aliases: dict | None = None) -> list[dict]:
    """Distinct ``(chain, token_address)`` seeds from the vault cache.

    One seed per (chain, underlying token address) across all cached vaults,
    deduplicated and lowercased, in first-seen order. Vaults whose chain is
    absent from ``chain_aliases`` are skipped (the live vault universe spans
    chains the collector cannot reach). Each seed resolves the CMC ``network``
    slug and the GeckoTerminal ``gecko_network`` id for the later passes.
    """
    gecko_aliases = gecko_aliases or {}
    seen: set[tuple] = set()
    seeds: list[dict] = []
    for vault in vault_payload.get("vaults") or []:
        chain = (vault.get("chain") or "").lower()
        if chain not in chain_aliases:
            continue
        for address in vault.get("underlyingTokens") or []:
            token_address = (address or "").lower()
            if not token_address:
                continue
            key = (chain, token_address)
            if key in seen:
                continue
            seen.add(key)
            seeds.append({
                "chain": chain,
                "token_address": token_address,
                "network": chain_aliases[chain],
                "gecko_network": gecko_aliases.get(chain),
            })
    return seeds


def pools_from_token_pairs(pairs: list[dict], seed: dict,
                           whitelist: set[str]) -> tuple[list[dict], dict]:
    """Turn one seed's token-pairs response into jobs + a ds-pair index.

    Keeps only pools whose counterparty (the non-target side) contract address is
    in ``whitelist`` (the USDC/USDT addresses for the seed's chain). Returns
    ``(jobs, ds_pairs)``: each job is a per-pool collection unit
    (``symbol``/``chain``/``dex``/``pool_address``/``token_address``/``network``/
    ``gecko_network``); ``ds_pairs`` maps lowercase pool address -> raw Dexscreener
    pair (reused for pooled amounts and the CMC-snapshot fallback). The target
    token's ``symbol`` is taken from the Dexscreener pair's matched side.
    """
    target = seed["token_address"].lower()
    jobs: list[dict] = []
    ds_pairs: dict[str, dict] = {}
    for pair in pairs or []:
        base = ((pair.get("baseToken") or {}).get("address") or "").lower()
        quote = ((pair.get("quoteToken") or {}).get("address") or "").lower()
        if target == base:
            counterparty = quote
            symbol = (pair.get("baseToken") or {}).get("symbol")
        elif target == quote:
            counterparty = base
            symbol = (pair.get("quoteToken") or {}).get("symbol")
        else:
            continue
        if counterparty not in whitelist:
            continue
        pool_address = (pair.get("pairAddress") or "").lower()
        if not pool_address:
            continue
        jobs.append({
            "symbol": symbol,
            "chain": seed["chain"],
            "dex": pair.get("dexId"),
            "pool_address": pool_address,
            "token_address": target,
            "network": seed["network"],
            "gecko_network": seed["gecko_network"],
        })
        ds_pairs[pool_address] = pair
    return jobs, ds_pairs


def history_targets(jobs: list[dict], snapshots: dict,
                    abnormal_price_delta: float) -> list[dict]:
    """The most-liquid price-sane *fetchable* job per ``(chain, token_address)``.

    ``snapshots`` maps a job's ``(chain, pool_address, token_address)`` key to its
    built snapshot (or None). A job is eligible when its snapshot has a numeric
    ``liquidity_usd`` and a ``price_usd`` within ``abnormal_price_delta`` of $1,
    AND its ``pool_address`` is a plain contract address (``is_contract_address``):
    collect-depeg-history fetches OHLCV by that address and GeckoTerminal 404s on
    Uniswap-v4 pool ids / Curve composites, so an un-fetchable pool is never chosen
    (a target with only un-fetchable pools gets no history pool and stays initial).
    For each target the highest-liquidity eligible job is returned (first-seen
    breaks ties); targets with no eligible job contribute nothing. Mirrors score's
    ``_valid_pools_by_liquidity`` so collection and scoring pick the same pool.
    """
    best: dict[tuple, dict] = {}
    best_liq: dict[tuple, float] = {}
    for job in jobs:
        snap = snapshots.get((job["chain"], job["pool_address"],
                              job["token_address"]))
        if not snap:
            continue
        price = snap.get("price_usd")
        liquidity = snap.get("liquidity_usd")
        if price is None or abs(price - 1) > abnormal_price_delta:
            continue
        if not liquidity:
            continue
        if not is_contract_address(job["pool_address"]):
            continue
        target = (job["chain"], job["token_address"])
        if target not in best_liq or liquidity > best_liq[target]:
            best_liq[target] = liquidity
            best[target] = job
    return list(best.values())


if __name__ == "__main__":
    raise SystemExit(
        "discovery.py provides pure discovery helpers imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py")
