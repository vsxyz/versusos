"""Pure, network-free deductive ranking for recommend: gate -> bucket -> order.

Consumes score-cache records (``vault_scores.json``'s ``scores``) and the
recommend config; produces the Pick-bucket structure the SKILL presents. The
gate is the cache-backed hard exclusion set (gate semantics in the recommend
references/investment-strategy.md §3); buckets are normalized_score bands. No network, no I/O — unit-tested
against tests/fixtures/.
"""
from __future__ import annotations

_BUCKETS = ("conservative", "balanced", "aggressive", "avoid")


def vault_yield(record):
    """yield = apyBase if non-null, else apy if non-null, else 0."""
    base = record.get("apyBase")
    if base is not None:
        return base
    apy = record.get("apy")
    return apy if apy is not None else 0


def gate_reasons(record, cfg):
    """Cache-backed hard-exclusion reasons for a record (empty list = survives)."""
    ex = cfg["exclusions"]
    reasons = []
    if (record.get("normalized_score") or 0) < ex["score_floor"]:
        reasons.append("score_floor")
    days = record.get("exploit_recent_days")
    if days is not None and days <= ex["exploit_window_days"]:
        reasons.append("recent_exploit")
    # recent_depeg is deep-only by score's construction (score emits it True only when basis=="deep")
    if ex.get("gate_depeg") and record.get("recent_depeg"):
        reasons.append("recent_depeg")
    if ex.get("gate_dynamic_zero"):
        dyn = (record.get("factors") or {}).get("dynamic") or {}
        if record.get("basis") == "deep" and dyn.get("points") == 0 and not dyn.get("stale"):
            reasons.append("dynamic_zero")
    return reasons


def classify(record, bands):
    """Map normalized_score to a bucket name (or None below ``avoid_min``)."""
    ns = record.get("normalized_score") or 0
    if ns >= bands["conservative_min"]:
        return "conservative"
    if ns >= bands["balanced_min"]:
        return "balanced"
    if ns >= bands["aggressive_min"]:
        return "aggressive"
    if ns >= bands["avoid_min"]:
        return "avoid"
    return None


def order_key(record):
    """Descending sort key for every bucket: APR first, TVL breaks ties.

    Band membership (set by classify) already encodes safety; within a band the
    higher-APR pool ranks first so the reps surface the best yield."""
    return (vault_yield(record), record.get("tvlUsd") or 0)


def select_reps(sorted_rows, n):
    """First n rows with a distinct 'project', preserving the input (APR) order.

    Fewer than n rows when the bucket has fewer than n distinct projects — never
    padded with another pool of an already-chosen project."""
    reps, seen = [], set()
    for r in sorted_rows:
        project = r.get("project")
        if project in seen:
            continue
        seen.add(project)
        reps.append(r)
        if len(reps) >= n:
            break
    return reps


def select_asset(records, asset, cfg):
    """Records for ``asset`` annotated with ``variant`` (symbol-match, not native)."""
    au = asset.upper()
    fam = {f.upper() for f in (cfg.get("asset_families") or {}).get(au, [])}
    out = []
    for r in records:
        ev = (r.get("evaluated_token") or "").upper()
        sym = (r.get("symbol") or "").upper()
        native = ev == au or ev in fam
        variant = (not native) and (au in sym)
        if native or variant:
            out.append({**r, "variant": variant})
    return out


def build_summary(excluded, cfg):
    """Exclusion disclosure: counts by reason, high-APY callouts, depeg list."""
    by_reason = {}
    for r in excluded:
        for reason in r["reasons"]:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    floor = cfg["display"]["high_apy_callout_apy"]
    high = sorted(
        ({"project": r.get("project"), "chain": r.get("chain"), "symbol": r.get("symbol"),
          "yield": vault_yield(r), "reasons": r["reasons"]}
         for r in excluded if vault_yield(r) >= floor),
        key=lambda c: c["yield"], reverse=True)
    depeg = [{"project": r.get("project"), "chain": r.get("chain"), "symbol": r.get("symbol"),
              "note": "possible pool-noise — F3"}
             for r in excluded if "recent_depeg" in r["reasons"]]
    return {"by_reason": by_reason, "high_apy_callouts": high, "depeg_excluded": depeg}


def bucketize(records, cfg, asset):
    """Full deductive result for one asset: buckets (sorted) + excluded + summary."""
    selected = select_asset(records, asset, cfg)
    buckets = {b: [] for b in _BUCKETS}
    excluded = []
    for r in selected:
        reasons = gate_reasons(r, cfg)
        if reasons:
            excluded.append({**r, "reasons": reasons})
            continue
        bucket = classify(r, cfg["bands"])
        if bucket:
            buckets[bucket].append(r)
    for rows in buckets.values():
        rows.sort(key=order_key, reverse=True)
    counts = {"candidates": len(selected),
              "survivors": sum(len(v) for v in buckets.values()),
              "excluded": len(excluded)}
    counts.update({b: len(buckets[b]) for b in _BUCKETS})
    reps = {b: select_reps(buckets[b], cfg["display"]["reps_per_bucket"]) for b in _BUCKETS}
    return {"asset": asset, "counts": counts, "buckets": buckets, "reps": reps,
            "excluded": excluded, "exclusion_summary": build_summary(excluded, cfg)}


if __name__ == "__main__":
    raise SystemExit(
        "ranking.py provides pure ranking helpers imported by recommend.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the recommender instead:  python scripts/recommend.py --asset USDT")
