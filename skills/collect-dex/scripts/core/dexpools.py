"""Pure, network-free shaping for discovered-DEX pool data.

Turns discovered jobs plus raw API responses (CMC v4 DEX pairs, Dexscreener
pooled amounts) into the output cache payload. No network and no I/O, so
everything here is testable against tests/fixtures/.
"""
from __future__ import annotations

import math


def _to_float(value):
    """Dexscreener sends prices as strings; missing/junk/non-finite becomes None."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def orient_snapshot(pair: dict, token_address: str) -> dict | None:
    """Normalize a CMC v4 DEX pair so fields refer to the target stablecoin.

    Matches ``token_address`` against the pair's base/quote asset contract
    addresses (case-insensitively — both sides are lowercased before
    comparing); returns None when it matches neither (wrong mapping entry —
    treated as a missing snapshot). CMC's ``price`` is the base asset's USD
    price and ``price_by_quote_asset`` the base priced in quote units, so when
    the target is the quote side: target-in-counterparty =
    1/price_by_quote_asset and target USD = price/price_by_quote_asset.
    Per-side pooled amounts are not served by this endpoint — they stay None
    until ``merge_pooled`` fills them from the Dexscreener supplemental pass.
    The full raw pair object (incl. holders/security_scan/taxes aux fields)
    is preserved under ``raw``.
    """
    token_address = (token_address or "").lower()
    base_address = (pair.get("base_asset_contract_address") or "").lower()
    quote_address = (pair.get("quote_asset_contract_address") or "").lower()
    if token_address == base_address:
        target_is_base = True
        counterparty = {"symbol": pair.get("quote_asset_symbol"),
                        "address": quote_address}
    elif token_address == quote_address:
        target_is_base = False
        counterparty = {"symbol": pair.get("base_asset_symbol"),
                        "address": base_address}
    else:
        return None

    quote = (pair.get("quote") or [{}])[0]
    base_price_usd = _to_float(quote.get("price"))
    base_in_quote = _to_float(quote.get("price_by_quote_asset"))
    if target_is_base:
        price_in_counterparty = base_in_quote
        target_price_usd = base_price_usd
    else:
        price_in_counterparty = 1 / base_in_quote if base_in_quote else None
        target_price_usd = (base_price_usd / base_in_quote
                            if base_price_usd is not None and base_in_quote
                            else None)

    return {
        "price_usd": target_price_usd,
        "price_in_counterparty": price_in_counterparty,
        "liquidity_usd": _to_float(quote.get("liquidity")),
        "pooled_target": None,
        "pooled_counterparty": None,
        "counterparty": counterparty,
        "volume_h24": _to_float(quote.get("volume_24h")),
        "raw": pair,
    }


def snapshot_from_dexscreener(ds_pair: dict, token_address: str) -> dict | None:
    """Build a snapshot from a Dexscreener pair when CMC does not index the pool.

    Mirrors ``orient_snapshot``'s orientation and price math (Dexscreener's
    ``priceUsd`` is the base asset's USD price and ``priceNative`` the base
    priced in quote units), so a fallback snapshot is field-compatible with a CMC
    one. ``source`` is ``"dexscreener"``. Returns None when ``token_address``
    matches neither side. Per-side pooled amounts come from the same pair via
    ``merge_pooled``.
    """
    token_address = (token_address or "").lower()
    base = ((ds_pair.get("baseToken") or {}).get("address") or "").lower()
    quote = ((ds_pair.get("quoteToken") or {}).get("address") or "").lower()
    if token_address == base:
        target_is_base = True
        counterparty = {"symbol": (ds_pair.get("quoteToken") or {}).get("symbol"),
                        "address": quote}
    elif token_address == quote:
        target_is_base = False
        counterparty = {"symbol": (ds_pair.get("baseToken") or {}).get("symbol"),
                        "address": base}
    else:
        return None

    base_price_usd = _to_float(ds_pair.get("priceUsd"))
    base_in_quote = _to_float(ds_pair.get("priceNative"))
    if target_is_base:
        price_in_counterparty = base_in_quote
        target_price_usd = base_price_usd
    else:
        price_in_counterparty = 1 / base_in_quote if base_in_quote else None
        target_price_usd = (base_price_usd / base_in_quote
                            if base_price_usd is not None and base_in_quote
                            else None)

    liquidity = ds_pair.get("liquidity") or {}
    volume = ds_pair.get("volume") or {}
    snapshot = {
        "price_usd": target_price_usd,
        "price_in_counterparty": price_in_counterparty,
        "liquidity_usd": _to_float(liquidity.get("usd")),
        "pooled_target": None,
        "pooled_counterparty": None,
        "counterparty": counterparty,
        "volume_h24": _to_float(volume.get("h24")),
        "raw": ds_pair,
        "source": "dexscreener",
    }
    return merge_pooled(snapshot, ds_pair, token_address)


def build_snapshot(job: dict, pairs_by_chain: dict,
                   ds_pairs_by_chain: dict | None) -> dict | None:
    """Snapshot for one job: CMC primary (+ DS pooled), else DS fallback.

    ``pairs_by_chain``: {chain: {pool address: raw CMC pair}}.
    ``ds_pairs_by_chain``: {chain: {pool address: raw Dexscreener pair}}. When CMC
    indexes the pool the CMC snapshot is used (``source="cmc"``) and pooled
    amounts are merged from the DS pair; otherwise the DS pair builds the whole
    snapshot (``source="dexscreener"``). None when neither source has the pool.
    """
    cmc_pair = (pairs_by_chain.get(job["chain"]) or {}).get(job["pool_address"])
    ds_pair = ((ds_pairs_by_chain or {}).get(job["chain"]) or {}).get(
        job["pool_address"])
    if cmc_pair:
        snapshot = orient_snapshot(cmc_pair, job["token_address"])
        if snapshot is not None:
            snapshot["source"] = "cmc"
            return merge_pooled(snapshot, ds_pair, job["token_address"])
    if ds_pair is not None:
        return snapshot_from_dexscreener(ds_pair, job["token_address"])
    return None


def merge_pooled(snapshot: dict | None, ds_pair: dict | None,
                 token_address: str) -> dict | None:
    """Fill pooled_* on a CMC snapshot from a Dexscreener pair (supplemental).

    CMC's quotes endpoint does not serve per-side pooled amounts, so this one
    field pair stays on Dexscreener (the migration's keep-what-CMC-lacks
    rule). Missing either input leaves the snapshot untouched.
    """
    if snapshot is None or ds_pair is None:
        return snapshot
    liquidity = ds_pair.get("liquidity") or {}
    base = ((ds_pair.get("baseToken") or {}).get("address") or "").lower()
    if (token_address or "").lower() == base:
        snapshot["pooled_target"] = liquidity.get("base")
        snapshot["pooled_counterparty"] = liquidity.get("quote")
    else:
        snapshot["pooled_target"] = liquidity.get("quote")
        snapshot["pooled_counterparty"] = liquidity.get("base")
    return snapshot


def assemble(jobs: list[dict], snapshots: dict, *, history_days: int,
             fetched_at: str, history_selected: set | None = None,
             min_pool_liquidity: float = 0) -> dict:
    """Assemble the output cache payload from discovered jobs.

    ``snapshots``: {(chain, pool_address, token_address): built snapshot or None}.
    ``history_selected``: the set of keys whose pool is the per-target history
    pool (flagged so collect-depeg-history knows which to fetch). OHLCV itself is
    no longer collected here — it lives in collect-depeg-history's cache. Each
    pool persists ``gecko_network`` so that skill can call GeckoTerminal.

    Only **score-relevant** pools are persisted: a pool is kept when it is
    ``history_selected`` (the depeg/dynamic reference) or its snapshot
    ``liquidity_usd`` is >= ``min_pool_liquidity`` (the Pool Liquidity factor's
    floor — keep this equal to score's ``pool_liquidity.min_pool_tvl`` so the cut
    is score-neutral). A pool below the floor that is not the history pool feeds no
    factor, so it is dropped; ``counts`` reports persisted vs dropped. With the
    default floor of 0, every snapshotted pool is kept (only snapshot-less,
    unselected pools drop).
    """
    selected = history_selected or set()
    by_symbol: dict[str, list[dict]] = {}
    counts = {
        "target_tokens": len({(j["chain"], j["token_address"]) for j in jobs}),
        "qualifying_pools": len(jobs),
        "snapshot_ok": 0,
        "persisted_pools": 0,
        "dropped_unscored": 0,
    }
    for job in jobs:
        key = (job["chain"], job["pool_address"], job["token_address"])
        snapshot = snapshots.get(key)
        if snapshot is not None:
            counts["snapshot_ok"] += 1
        liquidity = (snapshot or {}).get("liquidity_usd")
        scorable = (key in selected
                    or (liquidity is not None and liquidity >= min_pool_liquidity))
        if not scorable:
            counts["dropped_unscored"] += 1
            continue
        counts["persisted_pools"] += 1
        by_symbol.setdefault(job["symbol"], []).append({
            "chain": job["chain"],
            "dex": job["dex"],
            "pool_address": job["pool_address"],
            "token_address": job["token_address"],
            "gecko_network": job.get("gecko_network"),
            "snapshot": snapshot,
            "flags": {"history_selected": key in selected},
        })
    return {
        "source": "coinmarketcap-dex+dexscreener",
        "fetched_at": fetched_at,
        "history_window_days": history_days,
        "counts": counts,
        "stablecoins": [{"symbol": symbol, "pools": pools}
                        for symbol, pools in by_symbol.items()],
    }


if __name__ == "__main__":
    raise SystemExit(
        "dexpools.py provides pure shaping helpers imported by collect.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )
