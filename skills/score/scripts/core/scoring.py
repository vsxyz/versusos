"""Pure safety-score computation for collected vaults (points model).

Implements references/scoring-methodology.md: five factor point calculators
(contract & token safety, depeg, vault TVL, pool liquidity, dynamic) summed into
a raw 0-100 (initial) or 0-200 (deep) score, then a brand-wide exploit penalty
(-penalty_per * N, floored at 0), normalized to 0-100 for the grade. All step/tier
tables live in
config/scoring.json + config/contract_token_safety.json. Pure and network-free: every
input is a plain dict from the caches; recency math uses the DEX cache fetched_at
(passed in as ``fetched_at_epoch``) as "now".
"""
from __future__ import annotations

import datetime
import math
import re

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_contract_address(value: str | None) -> bool:
    """True only for a plain EVM contract address (``0x`` + 40 hex).

    Dexscreener's ``pairAddress`` is sometimes a 32-byte pool id (``0x`` + 64
    hex, Uniswap v4) or a hyphen-joined Curve/registry composite; GeckoTerminal
    404s on those, so depeg/dynamic read OHLCV only from a fetchable pool.
    Duplicated from collect-dex (skills are self-contained and never import from
    each other).
    """
    return bool(value and _ADDRESS_RE.match(value))


# --- table / recency lookup helpers (config-table driven, pure) ---


def _ceil2(value):
    """Round up to 2 decimals (72.7272 -> 72.73). round() first clears float dust."""
    return math.ceil(round(value * 100, 6)) / 100


def _table_lookup(value, table):
    """``table`` rows are [lower_bound, points] high->low; returns the points for
    the first band with ``value >= lower_bound`` (None / below all -> 0)."""
    if value is None:
        return 0
    for lower, points in table:
        if value >= lower:
            return points
    return 0


def _history_cap(history_days, caps):
    """``caps`` rows [{min_days, cap}] high->low; first min_days<=history_days."""
    for entry in caps:
        if history_days >= entry["min_days"]:
            return entry["cap"]
    return 0


def _depeg_penalty(days_ago, deductions):
    """``deductions`` rows [{max_days, penalty}] low->high; first match wins."""
    for entry in deductions:
        if days_ago <= entry["max_days"]:
            return entry["penalty"]
    return 0


def _recovery_points(held_seconds, recovery, full):
    """``recovery`` rows [held_upper, points] low->high; under the first matching
    upper wins, else ``full`` (held at/above the top band)."""
    for upper, points in recovery:
        if held_seconds < upper:
            return points
    return full


def _valid_pools_by_liquidity(pools, abnormal_delta):
    """Price-sane, GeckoTerminal-fetchable pools sorted by liquidity_usd, highest first.

    Excludes a pool whose snapshot price is missing or deviates from $1 by more
    than ``abnormal_delta`` (the doc's 'abnormal price pool -> exclude'), and a
    pool whose ``pool_address`` is not a plain contract address (Uniswap-v4 pool
    ids / Curve composites carry no GeckoTerminal OHLCV). Mirrors collect-dex's
    ``discovery.history_targets`` so collection and scoring pick the same pool.
    """
    valid = []
    for pool in pools:
        snap = pool.get("snapshot") or {}
        price = snap.get("price_usd")
        if price is None or abs(price - 1) > abnormal_delta:
            continue
        if not is_contract_address(pool.get("pool_address")):
            continue
        valid.append(pool)
    valid.sort(key=lambda pool: (pool.get("snapshot") or {}).get("liquidity_usd") or 0,
               reverse=True)
    return valid


# --- factor point calculators (one per scoring-methodology factor) ---


def vault_tvl_points(vault, config):
    """Vault TVL points from the configured step table."""
    return _table_lookup(vault.get("tvlUsd"), config["vault_tvl"]["table"])


def pool_liquidity_points(pools, config):
    """Pool-liquidity points: sum the USDC/USDT counterparty side over accepted
    pools (TVL >= min, whitelisted counterparty, sane price), then table-lookup.
    pooled_counterparty is already in whole-token units ~= USD."""
    cfg = config["pool_liquidity"]
    whitelist = set(cfg["counterparty_whitelist"])
    delta = cfg["abnormal_price_delta"]
    total = 0.0
    for pool in pools:
        snap = pool.get("snapshot") or {}
        liquidity = snap.get("liquidity_usd")
        price = snap.get("price_usd")
        pooled = snap.get("pooled_counterparty")
        counterparty = (snap.get("counterparty") or {}).get("symbol")
        if liquidity is None or liquidity < cfg["min_pool_tvl"]:
            continue
        if counterparty not in whitelist:
            continue
        if price is None or abs(price - 1) > delta:
            continue
        if pooled is None:
            continue
        total += pooled
    return _table_lookup(total, cfg["table"]) if total else 0


def depeg_points(pools, config, fetched_at_epoch):
    """Depeg-history points from the most-liquid pool's daily closes.

    Returns ``(points, available)``. Picks the most-liquid price-sane, fetchable
    pool that has daily history (un-fetchable Uniswap-v4 / Curve pools are excluded
    upstream); deducts per sub-threshold day by recency; caps by available
    history length. ``available`` is False when no pool carries daily OHLCV (the
    deep phase needs it for every evaluated target).

    A day counts as sub-peg only when its **close** holds below the threshold —
    not a momentary intraday low. DEX daily lows routinely wick well below peg on
    a single thin-liquidity tick (a genuinely-pegged stablecoin can print a 0.95
    low yet close at 1.00); reading the low instead falsely flags those, and
    structurally exempts tokens trading above $1. Transient intraday dips are the
    minute ``dynamic_points`` factor's job.
    """
    cfg = config["depeg"]
    candles = None
    for pool in _valid_pools_by_liquidity(pools, cfg["abnormal_price_delta"]):
        if pool.get("ohlcv_daily"):
            candles = pool["ohlcv_daily"]
            break
    if not candles:
        return 0, False
    cap = _history_cap(len(candles), cfg["history_caps"])
    threshold = cfg["threshold"]
    deduction = 0
    for candle in candles:
        close = candle[4]
        if close is None or close >= threshold:
            continue
        days_ago = (fetched_at_epoch - candle[0]) / 86400
        deduction += _depeg_penalty(days_ago, cfg["deductions"])
    return min(cap, max(0, cfg["max"] - deduction)), True


def dynamic_points(pools, config, fetched_at_epoch):
    """Dynamic (near-realtime peg) points from the 12h minute window.

    Returns ``(points, stale)``. Stateless recovery: the most recent
    sub-threshold candle's age maps onto the recovery ladder; no sub-threshold
    candle in the window -> full. ``stale`` is True when no usable minute candles
    are available (the cache lacked ohlcv_minute / window was empty).
    Note: ``stale`` is the inverse of ``depeg_points``' ``available`` -- True
    means minute data is absent.
    """
    cfg = config["dynamic"]
    delta = config["depeg"]["abnormal_price_delta"]
    candles = None
    for pool in _valid_pools_by_liquidity(pools, delta):
        if pool.get("ohlcv_minute"):
            candles = pool["ohlcv_minute"]
            break
    if not candles:
        return cfg["missing_points"], True
    window = cfg["window_hours"] * 3600
    in_window = [candle for candle in candles
                 if (fetched_at_epoch - candle[0]) <= window]
    if not in_window:
        return cfg["missing_points"], True
    threshold = cfg["threshold"]
    latest = in_window[0]
    if latest[3] is not None and latest[3] < threshold:
        return 0, False
    last_depeg_ts = None
    for candle in in_window:  # newest-first: first match is the most recent depeg
        if candle[3] is not None and candle[3] < threshold:
            last_depeg_ts = candle[0]
            break
    if last_depeg_ts is None:
        return cfg["full"], False
    held = fetched_at_epoch - last_depeg_ts
    return _recovery_points(held, cfg["recovery"], cfg["full"]), False


def contract_token_safety_points(vault, static_index, config):
    """Contract & Token Safety points from the static per-vault mapping.

    ``static_index`` maps a vault's ``pool`` id ->
    {"points": 0-15, "protocol_audit": 0-10, "token_audit": 0-5} from
    config/contract_token_safety.json, where ``points`` is the Audit Score
    (== protocol_audit + token_audit). An absent record scores 0 across the
    board. research-audit does not feed this factor (advisory-only in recommend).
    Only ``points`` enters the score; ``protocol_audit``/``token_audit`` ride
    along for output transparency (the protocol vs token split).
    """
    cfg = config["contract_token_safety"]
    record = (static_index or {}).get(vault.get("pool"))
    points = protocol_audit = token_audit = 0.0
    if record is not None:
        points = min(cfg["max"], float(record.get("points") or 0))
        protocol_audit = float(record.get("protocol_audit") or 0)
        token_audit = float(record.get("token_audit") or 0)
    return {
        "points": round(points, 2),
        "token_audit": round(token_audit, 2),
        "protocol_audit": round(protocol_audit, 2),
    }


# --- exploit, depeg-recency & grade signals (consumed by the recommend gate) ---


def exploit_count_for(vault, exploit_index):
    """(exploit_count, match) for a vault's protocol; unmatched -> (0, 'unmatched').

    'unmatched' means the protocol slug is absent from the hacks index, so no
    penalty is applied (the doc's 'unclear match -> do not penalize').
    """
    record = (exploit_index or {}).get(vault.get("project"))
    if record is None:
        return 0, "unmatched"
    return int(record.get("exploit_count") or 0), "matched"


def exploit_recent_days(vault, exploit_index, fetched_at_epoch):
    """Days from the most recent brand exploit event to ``fetched_at_epoch``.

    Returns None when the protocol has no recorded events. Event dates are
    ``"YYYY-MM-DD"``; the smallest non-negative age wins. Policy-free: the
    recommend gate applies its own window (e.g. <= 90 days).
    """
    record = (exploit_index or {}).get(vault.get("project")) or {}
    ages = []
    for event in record.get("events") or []:
        try:
            ts = datetime.datetime.strptime(event.get("date", ""), "%Y-%m-%d").replace(
                tzinfo=datetime.timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
        ages.append((fetched_at_epoch - ts) / 86400)
    nonneg = [a for a in ages if a >= 0]
    pool = nonneg or ages
    return int(min(pool)) if pool else None


def recent_depeg(pools, config, fetched_at_epoch):
    """True if the most-liquid fetchable pool's daily close held below the depeg
    threshold within ``recency_days``. Mirrors ``depeg_points`` pool selection and
    its close-based (not intraday-low) reading; policy-free signal the recommend
    gate consumes.
    """
    cfg = config["depeg"]
    window = cfg.get("recency_days", 30) * 86400
    candles = None
    for pool in _valid_pools_by_liquidity(pools, cfg["abnormal_price_delta"]):
        if pool.get("ohlcv_daily"):
            candles = pool["ohlcv_daily"]
            break
    if not candles:
        return False
    for candle in candles:
        close = candle[4]
        if close is not None and close < cfg["threshold"] and (fetched_at_epoch - candle[0]) <= window:
            return True
    return False


def grade_for(final_score, grades):
    """Grade label for a final score from the configured bands (high->low)."""
    for lower, label in grades:
        if final_score >= lower:
            return label
    return grades[-1][1]


# --- top-level orchestration ---


def score_vault(vault, pools_by_target, config, *, static_index=None,
                exploit_index=None, fetched_at_epoch=0):
    """Two-phase score for one vault against its matched DEX pools.

    score_1 = ceil2((cts + tvl + pool_liquidity) / score1_max * 100)   [0,100].
    When depeg + dynamic history is present for every evaluated target, the vault
    is "deep": score_2 = ceil2((depeg + dynamic) / score2_max * 100) is added, so
    final sits on 0-200. Otherwise the vault stays "initial" (0-100). DEX factors
    are per-target minimums (conservative). Final = max(0, base - penalty), where
    the exploit penalty scales with max_scale (penalty_per*N*(max_scale//100)) so
    each exploit is a uniform -penalty_per on normalized_score in both phases.
    """
    norm = config["normalization"]
    safety = contract_token_safety_points(vault, static_index, config)
    tvl = vault_tvl_points(vault, config)
    targets = sorted(pools_by_target)
    if targets:
        liquidity = min(pool_liquidity_points(pools_by_target[t], config)
                        for t in targets)
        depeg_pairs = [depeg_points(pools_by_target[t], config, fetched_at_epoch)
                       for t in targets]
        dyn_pairs = [dynamic_points(pools_by_target[t], config, fetched_at_epoch)
                     for t in targets]
        depeg_value, _ = min(depeg_pairs, key=lambda pair: pair[0])
        dynamic_value, dynamic_stale = min(dyn_pairs, key=lambda pair: pair[0])
        depeg_available = all(available for _, available in depeg_pairs)
        dynamic_available = all(not stale for _, stale in dyn_pairs)
        evaluated_token = ",".join(targets)
    else:
        liquidity = depeg_value = dynamic_value = 0
        depeg_available = dynamic_available = False
        dynamic_stale = True
        evaluated_token = ""
    raw1 = safety["points"] + tvl + liquidity
    score1 = _ceil2(raw1 / norm["score1_max"] * 100)
    deep = depeg_available and dynamic_available
    if deep:
        raw2 = depeg_value + dynamic_value
        score2 = _ceil2(raw2 / norm["score2_max"] * 100)
        base, basis, max_scale = score1 + score2, "deep", 200
    else:
        score2, base, basis, max_scale = None, score1, "initial", 100
    exploit_count, exploit_match = exploit_count_for(vault, exploit_index)
    recent_exploit_days = exploit_recent_days(vault, exploit_index, fetched_at_epoch)
    has_recent_depeg = deep and recent_depeg(
        [p for pools in pools_by_target.values() for p in pools], config, fetched_at_epoch)
    penalty = config["exploit"]["penalty_per"] * exploit_count * (max_scale // 100)
    final = max(0, base - penalty)
    normalized = _ceil2(final / max_scale * 100)
    return {
        "evaluated_token": evaluated_token,
        "score_1": score1,
        "score_2": score2,
        "basis": basis,
        "max_scale": max_scale,
        "raw_safety_score": round(raw1 + (depeg_value + dynamic_value if deep else 0), 2),
        "exploit_count": exploit_count,
        "exploit_recent_days": recent_exploit_days,
        "recent_depeg": has_recent_depeg,
        "exploit_penalty": penalty,
        "final_safety_score": round(final, 2),
        "normalized_score": normalized,
        "grade": grade_for(normalized, config["grades"]),
        "factors": {
            "contract_token_safety": safety,
            "depeg": depeg_value,
            "vault_tvl": tvl,
            "pool_liquidity": liquidity,
            "dynamic": {"points": dynamic_value, "stale": dynamic_stale},
        },
        "flags": {"dynamic_stale": dynamic_stale, "exploit_match": exploit_match},
        "dex_pools_matched": sum(len(p) for p in pools_by_target.values()),
    }


if __name__ == "__main__":
    raise SystemExit(
        "scoring.py provides pure scoring helpers imported by score.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the scorer instead:  python scripts/score.py"
    )
