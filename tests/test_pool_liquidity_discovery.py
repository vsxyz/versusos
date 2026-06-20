import json
import pathlib

from core import scoring

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCORING_CONFIG = ROOT / "skills" / "score" / "config" / "scoring.json"


def _pool(liq, pooled, counterparty, price=1.0):
    return {"snapshot": {"liquidity_usd": liq, "price_usd": price,
                         "pooled_counterparty": pooled,
                         "counterparty": {"symbol": counterparty}},
            "ohlcv_daily": None, "ohlcv_minute": None, "flags": {}}


def test_pool_liquidity_sums_only_qualifying_discovered_pools():
    config = json.loads(SCORING_CONFIG.read_text())
    pools = [
        _pool(1979006, 1235141, "USDC"),   # qualifies
        _pool(615669, 191229, "USDC"),     # qualifies
        _pool(367, 203, "USDT"),           # excluded: TVL < 50k
        _pool(3717627, 2253254, "bUSD0"),  # excluded: counterparty not whitelisted
    ]
    # 1,235,141 + 191,229 = 1,426,370 -> >= 1,000,000 -> 20 points
    assert scoring.pool_liquidity_points(pools, config) == 20


def test_pool_liquidity_enforces_each_exclusion_filter():
    config = json.loads(SCORING_CONFIG.read_text())
    # Two qualifying USDC pools sum to 249,000 counterparty -> band
    # [100000, 10] -> 10 pts, chosen just under the 250,000 boundary so any
    # wrongly-included pool crosses into a higher band and changes the score.
    qualifying = [_pool(400000, 200000, "USDC"), _pool(100000, 49000, "USDC")]
    assert scoring.pool_liquidity_points(qualifying, config) == 10

    sub_tvl = _pool(40000, 2000, "USDT")                   # TVL < $50k
    non_whitelisted = _pool(2000000, 1000000, "bUSD0")     # counterparty not USDC/USDT
    abnormal_price = _pool(1000000, 500000, "USDC", price=0.4)  # |price-1| > 0.5

    # Each excluded pool would push the total across a band boundary if its
    # filter were broken (-> 12, 20, 15 respectively); the score staying 10
    # proves each exclusion is enforced.
    for bad in (sub_tvl, non_whitelisted, abnormal_price):
        assert scoring.pool_liquidity_points(qualifying + [bad], config) == 10
