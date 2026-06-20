import datetime
import json
import pathlib

import pytest

from core import scoring

SCORING_CONFIG = (pathlib.Path(__file__).resolve().parents[1]
                  / "skills" / "score" / "config" / "scoring.json")

REF = 1_000_000_000  # fixed reference epoch for recency math

PLAIN_ADDR = "0x" + "b" * 40        # GeckoTerminal-fetchable (0x + 40 hex)
NONCONTRACT_ADDR = "0x" + "a" * 64  # Uniswap-v4 pool id — not fetchable


def load_config():
    return json.loads(SCORING_CONFIG.read_text())


def _daily_candle(days_ago, price):
    # depeg reads the daily close (index 4); the low mirrors it so the candle is
    # valid and the test's intended day-price is what the factor sees.
    return [REF - int(days_ago * 86400), 1.0, 1.0, price, price, 1.0]


def _minute_candle(seconds_ago, low):
    # dynamic reads the minute low (index 3) to catch transient intraday dips.
    return [REF - int(seconds_ago), 1.0, 1.0, low, 1.0, 1.0]


def test_table_lookup_picks_first_band_at_or_below_value():
    table = [[1000000, 20], [500000, 15], [0, 0]]
    assert scoring._table_lookup(2000000, table) == 20
    assert scoring._table_lookup(1000000, table) == 20   # half-open lower bound
    assert scoring._table_lookup(999999, table) == 15
    assert scoring._table_lookup(0, table) == 0
    assert scoring._table_lookup(None, table) == 0


def test_history_cap_picks_first_min_days_met():
    caps = [{"min_days": 180, "cap": 15}, {"min_days": 90, "cap": 12},
            {"min_days": 30, "cap": 8}, {"min_days": 1, "cap": 5}]
    assert scoring._history_cap(180, caps) == 15
    assert scoring._history_cap(120, caps) == 12
    assert scoring._history_cap(29, caps) == 5
    assert scoring._history_cap(0, caps) == 0


def test_depeg_penalty_buckets_by_recency():
    deductions = [{"max_days": 30, "penalty": 10}, {"max_days": 90, "penalty": 5},
                  {"max_days": 180, "penalty": 3}]
    assert scoring._depeg_penalty(10, deductions) == 10
    assert scoring._depeg_penalty(30, deductions) == 10
    assert scoring._depeg_penalty(31, deductions) == 5
    assert scoring._depeg_penalty(120, deductions) == 3
    assert scoring._depeg_penalty(200, deductions) == 0


def test_recovery_points_ladder():
    recovery = [[3600, 0], [21600, 10], [43200, 20]]
    assert scoring._recovery_points(0, recovery, 30) == 0
    assert scoring._recovery_points(3599, recovery, 30) == 0
    assert scoring._recovery_points(3600, recovery, 30) == 10
    assert scoring._recovery_points(21600, recovery, 30) == 20
    assert scoring._recovery_points(43200, recovery, 30) == 30


def test_valid_pools_sorted_by_liquidity_and_price_filtered():
    pools = [
        {"pool_address": PLAIN_ADDR, "snapshot": {"price_usd": 1.0, "liquidity_usd": 100}},
        {"pool_address": PLAIN_ADDR, "snapshot": {"price_usd": 1.0, "liquidity_usd": 900}},
        {"pool_address": PLAIN_ADDR, "snapshot": {"price_usd": 0.2, "liquidity_usd": 5000}},   # abnormal -> drop
        {"pool_address": PLAIN_ADDR, "snapshot": {"price_usd": None, "liquidity_usd": 5000}},  # no price -> drop
    ]
    valid = scoring._valid_pools_by_liquidity(pools, 0.5)
    assert [p["snapshot"]["liquidity_usd"] for p in valid] == [900, 100]


def test_valid_pools_excludes_non_contract_addresses():
    # A more-liquid pool with a non-contract address (Uniswap-v4 id / Curve
    # composite) is excluded so depeg/dynamic read OHLCV only from a
    # GeckoTerminal-fetchable pool.
    pools = [
        {"pool_address": NONCONTRACT_ADDR,
         "snapshot": {"price_usd": 1.0, "liquidity_usd": 9000}},   # most liquid, unfetchable
        {"pool_address": PLAIN_ADDR,
         "snapshot": {"price_usd": 1.0, "liquidity_usd": 100}},
    ]
    valid = scoring._valid_pools_by_liquidity(pools, 0.5)
    assert [p["pool_address"] for p in valid] == [PLAIN_ADDR]


def test_vault_tvl_points_bands():
    config = load_config()
    assert scoring.vault_tvl_points({"tvlUsd": 2_000_000}, config) == 20
    assert scoring.vault_tvl_points({"tvlUsd": 800_000}, config) == 18
    assert scoring.vault_tvl_points({"tvlUsd": 600_000}, config) == 15
    assert scoring.vault_tvl_points({"tvlUsd": 300_000}, config) == 10
    assert scoring.vault_tvl_points({"tvlUsd": 200_000}, config) == 8
    assert scoring.vault_tvl_points({"tvlUsd": 120_000}, config) == 5
    assert scoring.vault_tvl_points({"tvlUsd": 50_000}, config) == 0
    assert scoring.vault_tvl_points({}, config) == 0


def test_pool_liquidity_sums_whitelisted_counterparty_then_bands():
    config = load_config()
    pools = [
        {"snapshot": {"liquidity_usd": 5_000_000, "price_usd": 1.0,
                      "pooled_counterparty": 600_000,
                      "counterparty": {"symbol": "USDT"}}},
        {"snapshot": {"liquidity_usd": 5_000_000, "price_usd": 1.0,
                      "pooled_counterparty": 200_000,
                      "counterparty": {"symbol": "USDC"}}},
    ]
    # 600k + 200k = 800k -> 18 band
    assert scoring.pool_liquidity_points(pools, config) == 18


def test_pool_liquidity_excludes_small_nonwhitelist_and_abnormal_pools():
    config = load_config()
    pools = [
        {"snapshot": {"liquidity_usd": 10_000, "price_usd": 1.0,
                      "pooled_counterparty": 9_000,
                      "counterparty": {"symbol": "USDT"}}},
        {"snapshot": {"liquidity_usd": 5_000_000, "price_usd": 1.0,
                      "pooled_counterparty": 900_000,
                      "counterparty": {"symbol": "DAI"}}},
        {"snapshot": {"liquidity_usd": 5_000_000, "price_usd": 0.3,
                      "pooled_counterparty": 900_000,
                      "counterparty": {"symbol": "USDT"}}},
    ]
    assert scoring.pool_liquidity_points(pools, config) == 0


def test_pool_liquidity_no_pools_is_zero():
    assert scoring.pool_liquidity_points([], load_config()) == 0


def _depeg_pool(candles, pool_address=PLAIN_ADDR):
    return {"pool_address": pool_address,
            "snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000},
            "ohlcv_daily": candles}


def test_depeg_full_when_no_subpeg_days():
    config = load_config()
    pools = [_depeg_pool([_daily_candle(d, 0.999) for d in range(180)])]
    assert scoring.depeg_points(pools, config, REF) == (15, True)


def test_depeg_cumulative_recency_deductions():
    config = load_config()
    candles = [_daily_candle(d, 0.999) for d in range(180)]
    candles[0] = _daily_candle(60, 0.97)    # 30-90d -> -5
    candles[1] = _daily_candle(120, 0.97)   # 90-180d -> -3
    # 15 - 5 - 3 = 7
    assert scoring.depeg_points([_depeg_pool(candles)], config, REF) == (7, True)


def test_depeg_history_cap_for_short_history():
    config = load_config()
    pools = [_depeg_pool([_daily_candle(d, 0.999) for d in range(40)])]
    assert scoring.depeg_points(pools, config, REF) == (8, True)   # 40 candles -> cap 8


def test_depeg_returns_points_and_availability():
    config = load_config()
    full = [_depeg_pool([_daily_candle(d, 0.999) for d in range(180)])]
    assert scoring.depeg_points(full, config, REF) == (15, True)
    assert scoring.depeg_points([_depeg_pool([])], config, REF) == (0, False)
    assert scoring.depeg_points([], config, REF) == (0, False)


def test_depeg_uses_fetchable_pool_over_more_liquid_noncontract():
    config = load_config()
    # The more-liquid pool is a non-contract address (un-fetchable) carrying a
    # depegged day; the fetchable pool is clean. depeg must use the fetchable pool.
    noncontract = _depeg_pool([_daily_candle(d, 0.999) for d in range(180)],
                              pool_address=NONCONTRACT_ADDR)
    noncontract["snapshot"]["liquidity_usd"] = 9_000_000      # most liquid
    noncontract["ohlcv_daily"][0] = _daily_candle(1, 0.90)    # would deduct if used
    fetchable = _depeg_pool([_daily_candle(d, 0.999) for d in range(180)])
    assert scoring.depeg_points([noncontract, fetchable], config, REF) == (15, True)


def test_depeg_reads_daily_close_not_intraday_low():
    # A day that wicks below 0.98 intraday but closes back at peg is NOT a depeg
    # day — the daily factor reads the close (sustained peg); transient intraday
    # dips are the minute 'dynamic' factor's job. Regression: USDC's DEX daily
    # lows wick to ~0.95 while closing ~1.0, which used to score depeg=0.
    config = load_config()
    wick = [REF - 13 * 86400, 1.0, 1.0, 0.95, 0.999, 1.0]  # low 0.95, close 0.999
    candles = [wick] + [_daily_candle(d, 0.999) for d in range(1, 180)]
    assert scoring.depeg_points([_depeg_pool(candles)], config, REF) == (15, True)


def test_depeg_counts_day_whose_close_is_below_threshold():
    # A genuine sub-peg day (the close itself holds below 0.98) is still deducted
    # by recency — close-based detection still catches real depegs.
    config = load_config()
    sustained = [REF - 13 * 86400, 1.0, 1.0, 0.95, 0.97, 1.0]  # close 0.97, <=30d -> -10
    candles = [sustained] + [_daily_candle(d, 0.999) for d in range(1, 180)]
    assert scoring.depeg_points([_depeg_pool(candles)], config, REF) == (5, True)


def test_ceil2_rounds_up_to_two_decimals():
    assert scoring._ceil2(40 / 55 * 100) == 72.73
    assert scoring._ceil2(30 / 55 * 100) == 54.55
    assert scoring._ceil2(100.0) == 100.0


def _dynamic_pool(candles, pool_address=PLAIN_ADDR):
    return {"pool_address": pool_address,
            "snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000},
            "ohlcv_minute": candles}


def test_dynamic_full_when_no_depeg_in_window():
    config = load_config()
    candles = [_minute_candle(s, 0.999) for s in range(0, 12 * 3600, 60)]
    assert scoring.dynamic_points([_dynamic_pool(candles)], config, REF) == (30, False)


def test_dynamic_zero_when_latest_candle_depegged():
    config = load_config()
    candles = [_minute_candle(0, 0.97)] + [_minute_candle(s, 0.999)
                                           for s in range(60, 3600, 60)]
    assert scoring.dynamic_points([_dynamic_pool(candles)], config, REF) == (0, False)


def test_dynamic_recovery_stage_from_held_duration():
    config = load_config()
    # most recent depeg 7200s (2h) ago, clean since -> [1h,6h) -> 10
    candles = [_minute_candle(s, 0.999) for s in range(0, 7200, 60)]
    candles.append(_minute_candle(7200, 0.97))
    candles += [_minute_candle(s, 0.999) for s in range(7260, 12 * 3600, 60)]
    assert scoring.dynamic_points([_dynamic_pool(candles)], config, REF) == (10, False)


def test_dynamic_stale_when_minute_history_missing():
    config = load_config()
    assert scoring.dynamic_points([_dynamic_pool(None)], config, REF) == (0, True)
    assert scoring.dynamic_points([], config, REF) == (0, True)


def test_contract_token_safety_zero_without_static_mapping():
    config = load_config()
    assert scoring.contract_token_safety_points(
        {"pool": "v1"}, {}, config) == {"points": 0, "token_audit": 0, "protocol_audit": 0}


def test_contract_token_safety_reads_static_mapping_capped():
    config = load_config()
    static_index = {"v1": {"points": 12}, "v2": {"points": 99}}
    assert scoring.contract_token_safety_points({"pool": "v1"}, static_index, config)["points"] == 12
    assert scoring.contract_token_safety_points({"pool": "v2"}, static_index, config)["points"] == 15  # capped


def test_contract_token_safety_surfaces_protocol_and_token_subfields():
    config = load_config()
    static_index = {"v1": {"points": 15, "protocol_audit": 10, "token_audit": 5},
                    "v2": {"points": 99, "protocol_audit": 10, "token_audit": 4}}
    assert scoring.contract_token_safety_points({"pool": "v1"}, static_index, config) == {
        "points": 15, "token_audit": 5, "protocol_audit": 10}
    # points still caps at max=15; the subfields ride along verbatim
    assert scoring.contract_token_safety_points({"pool": "v2"}, static_index, config) == {
        "points": 15, "token_audit": 4, "protocol_audit": 10}


def test_exploit_count_matched_and_unmatched():
    index = {"aave-v3": {"exploit_count": 2}}
    assert scoring.exploit_count_for({"project": "aave-v3"}, index) == (2, "matched")
    assert scoring.exploit_count_for({"project": "ghost"}, index) == (0, "unmatched")
    assert scoring.exploit_count_for({"project": "aave-v3"}, {}) == (0, "unmatched")


def test_grade_for_bands():
    grades = load_config()["grades"]
    assert scoring.grade_for(95, grades) == "Safe"
    assert scoring.grade_for(80, grades) == "Safe"
    assert scoring.grade_for(79, grades) == "Moderate"
    assert scoring.grade_for(50, grades) == "Aggressive"
    assert scoring.grade_for(30, grades) == "High Risk"
    assert scoring.grade_for(0, grades) == "Avoid"


def test_score_vault_sums_factors_applies_penalty_and_grade():
    config = load_config()
    vault = {"project": "aave-v3", "pool": "p-aave", "tvlUsd": 2_000_000}   # tvl -> 20
    pools_by_target = {"USDC": [{
        "pool_address": PLAIN_ADDR,
        "snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000_000,
                     "pooled_counterparty": 1_200_000,                      # liq -> 20
                     "counterparty": {"symbol": "USDT"}},
        "ohlcv_daily": [_daily_candle(d, 0.999) for d in range(180)],       # depeg -> 15
        "ohlcv_minute": [_minute_candle(s, 0.999)
                         for s in range(0, 12 * 3600, 60)],                 # dynamic -> 30
    }]}
    exploit_index = {"aave-v3": {"exploit_count": 1}}                       # -15
    record = scoring.score_vault(
        vault, pools_by_target, config, static_index={},
        exploit_index=exploit_index, fetched_at_epoch=REF)
    # score_1 = (0+20+20)/55*100 -> 72.73 ; score_2 = (15+30)/45*100 -> 100.0
    assert record["basis"] == "deep"
    assert record["raw_safety_score"] == 85.0      # factor sum 0+20+15+20+30
    assert record["exploit_penalty"] == 30         # deep: 15 * 1 * (200//100)
    assert record["final_safety_score"] == 142.73  # 72.73+100.0-30
    assert record["normalized_score"] == 71.37   # ceil2(142.73/200*100)
    assert record["grade"] == "Moderate"          # 71.37 in [65,80)
    assert record["factors"]["dynamic"] == {"points": 30, "stale": False}
    assert record["exploit_count"] == 1
    assert record["evaluated_token"] == "USDC"
    assert record["dex_pools_matched"] == 1
    assert record["factors"]["contract_token_safety"]["points"] == 0
    assert record["flags"]["exploit_match"] == "matched"


def test_exploit_penalty_uniform_across_basis():
    """One exploit costs a uniform 15 normalized points whether the vault is
    initial (0-100) or deep (0-200). The native penalty scales with max_scale
    (-15 initial, -30 deep), so opting into the deep score no longer dilutes the
    exploit penalty (pre-fix the deep drop was only 7.5: 86.37 -> 78.87)."""
    config = load_config()
    vault = {"project": "p", "pool": "p1", "tvlUsd": 2_000_000}   # tvl 20
    snap = {"price_usd": 1.0, "liquidity_usd": 1_000_000,
            "pooled_counterparty": 1_200_000,
            "counterparty": {"symbol": "USDT"}}                   # liq 20
    initial_pools = {"USDC": [{"snapshot": snap}]}
    deep_pools = {"USDC": [{
        "pool_address": PLAIN_ADDR, "snapshot": snap,
        "ohlcv_daily": [_daily_candle(d, 0.999) for d in range(180)],   # depeg 15
        "ohlcv_minute": [_minute_candle(s, 0.999)
                         for s in range(0, 12 * 3600, 60)],             # dynamic 30
    }]}
    one_exploit = {"p": {"exploit_count": 1}}

    def normalized(pools, exploit_index):
        return scoring.score_vault(
            vault, pools, config, static_index={},
            exploit_index=exploit_index, fetched_at_epoch=REF)["normalized_score"]

    assert normalized(initial_pools, {}) == 72.73
    assert normalized(initial_pools, one_exploit) == 57.73    # -15
    assert normalized(deep_pools, {}) == 86.37
    assert normalized(deep_pools, one_exploit) == 71.37       # -15 (not -7.5)


def test_score_vault_no_pools_zeroes_dex_factors():
    config = load_config()
    record = scoring.score_vault(
        {"project": "x", "pool": "p-x", "tvlUsd": 2_000_000}, {}, config, static_index={})
    assert record["factors"]["depeg"] == 0
    assert record["factors"]["pool_liquidity"] == 0
    assert record["factors"]["dynamic"] == {"points": 0, "stale": True}
    assert record["raw_safety_score"] == 20.0   # tvl only
    assert record["basis"] == "initial"
    assert record["score_1"] == 36.37   # (0+20+0)/55*100 = 36.3636.. -> ceil2 36.37
    assert record["final_safety_score"] == 36.37
    assert record["evaluated_token"] == ""
    assert record["flags"]["exploit_match"] == "unmatched"


def test_score_vault_initial_basis_rescales_55_to_100():
    config = load_config()
    vault = {"project": "p", "pool": "p1", "tvlUsd": 2_000_000}   # tvl 20
    pools = {"USDC": [{"snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000_000,
                                    "pooled_counterparty": 1_200_000,
                                    "counterparty": {"symbol": "USDT"}}}]}  # liq 20, no history
    record = scoring.score_vault(vault, pools, config, static_index={},
                                 fetched_at_epoch=REF)
    assert record["basis"] == "initial"
    assert record["max_scale"] == 100
    assert record["score_1"] == 72.73        # (0+20+20)/55*100, ceil2
    assert record["score_2"] is None
    assert record["final_safety_score"] == 72.73


def test_score_vault_deep_basis_adds_second_100():
    config = load_config()
    vault = {"project": "p", "pool": "p1", "tvlUsd": 2_000_000}
    pools = {"USDC": [{
        "pool_address": PLAIN_ADDR,
        "snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000_000,
                     "pooled_counterparty": 1_200_000,
                     "counterparty": {"symbol": "USDT"}},
        "ohlcv_daily": [_daily_candle(d, 0.999) for d in range(180)],   # depeg 15
        "ohlcv_minute": [_minute_candle(s, 0.999)
                         for s in range(0, 12 * 3600, 60)],             # dynamic 30
    }]}
    record = scoring.score_vault(vault, pools, config, static_index={},
                                 fetched_at_epoch=REF)
    assert record["basis"] == "deep"
    assert record["max_scale"] == 200
    assert record["score_1"] == 72.73
    assert record["score_2"] == 100.0        # (15+30)/45*100
    assert record["final_safety_score"] == 172.73
    assert record["normalized_score"] == 86.37   # ceil2(172.73/200*100)


def test_score_vault_deep_is_set_by_availability_and_score_2_is_additive_only():
    """'deep' comes from data availability, not score level: a pool WITH both
    daily+minute history but a depeg event is still deep, its score_2 sits below
    100, and (no exploit) final = score_1 + score_2 -- never a deduction below
    score_1."""
    config = load_config()
    vault = {"project": "p", "pool": "p1", "tvlUsd": 2_000_000}   # tvl 20
    daily = [_daily_candle(d, 0.999) for d in range(180)]
    daily[0] = _daily_candle(60, 0.97)    # 30-90d -> -5
    daily[1] = _daily_candle(120, 0.97)   # 90-180d -> -3   (depeg 15-5-3 = 7)
    pools = {"USDC": [{
        "pool_address": PLAIN_ADDR,
        "snapshot": {"price_usd": 1.0, "liquidity_usd": 1_000_000,
                     "pooled_counterparty": 1_200_000,
                     "counterparty": {"symbol": "USDT"}},        # liq 20
        "ohlcv_daily": daily,
        "ohlcv_minute": [_minute_candle(s, 0.999)
                         for s in range(0, 12 * 3600, 60)],      # clean -> dynamic 30
    }]}
    record = scoring.score_vault(vault, pools, config, static_index={},
                                 fetched_at_epoch=REF)
    assert record["basis"] == "deep"             # availability, not score level
    assert record["score_1"] == 72.73
    assert record["score_2"] == 82.23            # ceil2((7+30)/45*100), 0 < x < 100
    assert 0 < record["score_2"] < 100
    # additive-only: final is score_1 + score_2, never below score_1
    assert record["final_safety_score"] == 154.96
    assert record["final_safety_score"] == record["score_1"] + record["score_2"]
    assert record["final_safety_score"] > record["score_1"]


def _epoch(d):
    return datetime.datetime.strptime(d, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc).timestamp()


def test_exploit_recent_days_returns_min_age_or_none():
    idx = {"acme": {"events": [{"date": "2026-03-12"}, {"date": "2026-06-01"}]}}
    now = _epoch("2026-06-17")
    assert scoring.exploit_recent_days({"project": "acme"}, idx, now) == 16
    assert scoring.exploit_recent_days({"project": "nope"}, idx, now) is None
    assert scoring.exploit_recent_days({"project": "acme"}, {"acme": {"events": []}}, now) is None


def test_recent_depeg_true_when_daily_close_below_threshold_in_window():
    now = _epoch("2026-06-17")
    cfg = {"depeg": {"abnormal_price_delta": 0.1, "threshold": 0.98, "recency_days": 30}}
    pool = {"pool_address": "0x" + "a" * 40,
            "snapshot": {"price_usd": 1.0, "liquidity_usd": 10_000_000},
            "ohlcv_daily": [[_epoch("2026-06-05"), 1.0, 1.0, 0.95, 0.96, 1]]}  # close 0.96
    assert scoring.recent_depeg([pool], cfg, now) is True
    # intraday wick (low 0.9663) but the close held at peg -> NOT a recent depeg.
    wick = {**pool, "ohlcv_daily": [[_epoch("2026-06-05"), 1.0, 1.0, 0.9663, 1.0, 1]]}
    assert scoring.recent_depeg([wick], cfg, now) is False
    old = {**pool, "ohlcv_daily": [[_epoch("2026-01-31"), 1.0, 1.0, 0.95, 0.95, 1]]}
    assert scoring.recent_depeg([old], cfg, now) is False  # outside 30d window
    healthy = {**pool, "ohlcv_daily": [[_epoch("2026-06-05"), 1.0, 1.0, 0.999, 0.999, 1]]}
    assert scoring.recent_depeg([healthy], cfg, now) is False  # close never below threshold
