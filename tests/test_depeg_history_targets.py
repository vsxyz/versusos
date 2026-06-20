from core import targets

DEX = {"stablecoins": [
    {"symbol": "USDC", "pools": [
        {"chain": "ethereum", "pool_address": "0xa", "token_address": "0xusdc",
         "gecko_network": "eth", "flags": {"history_selected": True}},
        {"chain": "ethereum", "pool_address": "0xb", "token_address": "0xusdc",
         "gecko_network": "eth", "flags": {"history_selected": False}},  # not selected
    ]},
    {"symbol": "USDT", "pools": [
        {"chain": "base", "pool_address": "0xc", "token_address": "0xusdt",
         "gecko_network": "base", "flags": {"history_selected": True}},
    ]},
]}
SCORES = [
    {"pool": "v1", "symbol": "USDC", "chain": "ethereum"},
    {"pool": "v2", "symbol": "USDT", "chain": "base"},
    {"pool": "v3", "symbol": "USDT", "chain": "ethereum"},   # no matching pool
]


def test_select_targets_top_n_picks_history_selected_pools_on_chain():
    out = targets.select_targets(SCORES, DEX, top_n=1)
    assert out == [{"chain": "ethereum", "pool_address": "0xa",
                    "token_address": "0xusdc", "gecko_network": "eth", "symbol": "USDC"}]


def test_select_targets_dedupes_and_skips_unmatched():
    out = targets.select_targets(SCORES, DEX, top_n=10)
    keys = [(t["pool_address"]) for t in out]
    assert keys == ["0xa", "0xc"]   # 0xb not selected; v3 has no base/eth USDT-on-eth pool
