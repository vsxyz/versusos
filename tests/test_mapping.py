import json
import pathlib

import pytest

from core import mapping

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def dex_payload():
    return load_fixture("dex_pools_sample.json")


def test_vault_token_symbols_splits_and_uppercases():
    assert mapping.vault_token_symbols({"symbol": "USDC-USDT"}) == ["USDC", "USDT"]
    assert mapping.vault_token_symbols({"symbol": "usdc"}) == ["USDC"]
    assert mapping.vault_token_symbols({}) == []


def test_build_pool_index_none_payload_is_empty():
    assert mapping.build_pool_index(None) == {}


def test_build_pool_index_groups_pools_by_symbol(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    assert set(index) == {"USDC", "USDT"}
    assert len(index["USDC"]) == 3
    assert len(index["USDT"]) == 1


def test_match_pools_chain_match_is_case_insensitive(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    vault = {"symbol": "USDC", "chain": "Ethereum"}
    pools = mapping.match_pools(vault, index)
    assert [p["pool_address"] for p in pools] == [
        "0x1111111111111111111111111111111111111111",
        "0xpool-usdc-eth-2",
    ]


def test_match_pools_pair_vault_gets_union_of_both_tokens(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    vault = {"symbol": "USDC-USDT", "chain": "Ethereum"}
    pools = mapping.match_pools(vault, index)
    assert [p["pool_address"] for p in pools] == [
        "0x1111111111111111111111111111111111111111",
        "0xpool-usdc-eth-2",
        "0xpool-usdt-eth-1",
    ]


def test_match_pools_unknown_symbol_or_chain_is_empty(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    assert mapping.match_pools({"symbol": "FRAX", "chain": "Ethereum"}, index) == []
    assert mapping.match_pools({"symbol": "USDC", "chain": "Polygon"}, index) == []


def test_match_pools_by_target_groups_by_symbol(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    grouped = mapping.match_pools_by_target(
        {"symbol": "USDC-USDT", "chain": "Ethereum"}, index)
    assert set(grouped) == {"USDC", "USDT"}
    assert [p["pool_address"] for p in grouped["USDC"]] == [
        "0x1111111111111111111111111111111111111111", "0xpool-usdc-eth-2"]
    assert [p["pool_address"] for p in grouped["USDT"]] == ["0xpool-usdt-eth-1"]


def test_match_pools_by_target_unknown_is_empty(dex_payload):
    index = mapping.build_pool_index(dex_payload)
    assert mapping.match_pools_by_target(
        {"symbol": "USDC", "chain": "Polygon"}, index) == {}


def test_merge_history_fills_ohlcv_by_pool_key():
    pool = {"chain": "ethereum", "pool_address": "0xa", "token_address": "0xusdc"}
    index = {"USDC": [pool]}
    history = {"by_pool": {"ethereum|0xa|0xusdc": {
        "ohlcv_daily": [[1, 1, 1, 1, 1, 1]], "ohlcv_minute": [[2, 1, 1, 1, 1, 1]]}}}
    mapping.merge_history(index, history)
    assert pool["ohlcv_daily"] == [[1, 1, 1, 1, 1, 1]]
    assert pool["ohlcv_minute"] == [[2, 1, 1, 1, 1, 1]]


def test_merge_history_leaves_unmatched_pools_untouched():
    pool = {"chain": "ethereum", "pool_address": "0xz", "token_address": "0xusdc"}
    mapping.merge_history({"USDC": [pool]}, {"by_pool": {}})
    assert "ohlcv_daily" not in pool


def test_merge_history_none_payload_is_noop():
    pool = {"chain": "ethereum", "pool_address": "0xa", "token_address": "0xusdc"}
    mapping.merge_history({"USDC": [pool]}, None)
    assert "ohlcv_daily" not in pool
