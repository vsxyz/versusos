import json
import pathlib

from core import ranking

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CFG = json.loads((pathlib.Path(__file__).parents[1] /
                  "skills/recommend/config/recommend.json").read_text())
RECORDS = json.loads((FIXTURES / "recommend_scores_sample.json").read_text())["scores"]


def _bz():
    return ranking.bucketize(RECORDS, CFG, "USDT")


def test_select_asset_native_vs_variant_and_excludes_other_assets():
    sel = ranking.select_asset(RECORDS, "USDT", CFG)
    pools = {r["pool"]: r["variant"] for r in sel}
    assert "other" not in pools           # USDC excluded
    assert pools["c1"] is False           # native
    assert pools["var1"] is True          # USDT0 -> variant


def test_classify_uses_bands():
    assert ranking.classify({"normalized_score": 80}, CFG["bands"]) == "conservative"
    assert ranking.classify({"normalized_score": 79}, CFG["bands"]) == "balanced"
    assert ranking.classify({"normalized_score": 64}, CFG["bands"]) == "aggressive"
    assert ranking.classify({"normalized_score": 49}, CFG["bands"]) == "avoid"
    assert ranking.classify({"normalized_score": 29}, CFG["bands"]) is None


def test_gate_reasons_each_predicate():
    by = {r["pool"]: r for r in RECORDS}
    assert ranking.gate_reasons(by["x_low"], CFG) == ["score_floor"]
    assert ranking.gate_reasons(by["x_exp"], CFG) == ["recent_exploit"]
    assert ranking.gate_reasons(by["x_dep"], CFG) == ["recent_depeg"]
    assert ranking.gate_reasons(by["x_dyn"], CFG) == ["dynamic_zero"]
    assert ranking.gate_reasons(by["c1"], CFG) == []


def test_bucketize_buckets_sorted_and_exclude_gated():
    out = _bz()
    # excluded pools are absent from buckets
    bucket_pools = {r["pool"] for b in out["buckets"].values() for r in b}
    assert {"x_low", "x_exp", "x_dep", "x_dyn"}.isdisjoint(bucket_pools)
    # conservative sorted by APR (yield) desc — c2 apyBase 6 > c1 apyBase 5
    assert [r["pool"] for r in out["buckets"]["conservative"]] == ["c2", "c1"]
    # aggressive sorted by yield desc
    assert [r["pool"] for r in out["buckets"]["aggressive"]] == ["a1", "a2", "var1"]
    assert out["counts"]["excluded"] == 4


def test_exclusion_summary_high_apy_and_depeg_list():
    s = _bz()["exclusion_summary"]
    assert s["by_reason"] == {"score_floor": 1, "recent_exploit": 1,
                              "recent_depeg": 1, "dynamic_zero": 1}
    callouts = {c["project"] for c in s["high_apy_callouts"]}
    assert callouts == {"lowco", "expco"}            # APY 28, 30 >= 15
    assert [d["project"] for d in s["depeg_excluded"]] == ["depco"]
    assert s["depeg_excluded"][0]["note"] == "possible pool-noise — F3"


def test_order_key_is_apr_first():
    high_apr_low_safety = {"apyBase": 20.0, "normalized_score": 51.0, "tvlUsd": 1}
    low_apr_high_safety = {"apyBase": 4.0, "normalized_score": 99.0, "tvlUsd": 1}
    rows = [low_apr_high_safety, high_apr_low_safety]
    rows.sort(key=ranking.order_key, reverse=True)
    assert rows[0] is high_apr_low_safety


def test_select_reps_distinct_projects():
    rows = [  # already APR-sorted; top two share a project
        {"pool": "p1a", "project": "alpha", "apyBase": 20.0},
        {"pool": "p1b", "project": "alpha", "apyBase": 18.0},
        {"pool": "p2", "project": "beta", "apyBase": 15.0},
    ]
    reps = ranking.select_reps(rows, 2)
    assert [r["pool"] for r in reps] == ["p1a", "p2"]


def test_select_reps_fallback_when_one_project():
    rows = [
        {"pool": "p1a", "project": "alpha", "apyBase": 20.0},
        {"pool": "p1b", "project": "alpha", "apyBase": 18.0},
    ]
    reps = ranking.select_reps(rows, 2)
    assert [r["pool"] for r in reps] == ["p1a"]


def test_bucketize_emits_reps_deduped():
    out = _bz()
    n = CFG["display"]["reps_per_bucket"]
    cons = out["reps"]["conservative"]
    assert len(cons) <= n
    assert len({r["project"] for r in cons}) == len(cons)   # distinct projects
    assert [r["pool"] for r in out["buckets"]["conservative"]] == ["c2", "c1"]
