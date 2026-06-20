import json
import pathlib

import pytest

from core import dexpools

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

USD0 = "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5"
USDC_ADDR = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _pairs_by_chain():
    pairs = load_fixture("cmc_pair_quotes_sample.json")["data"]
    return {"ethereum": {pair["contract_address"].lower(): pair for pair in pairs}}


def test_to_float_rejects_non_finite():
    assert dexpools._to_float("nan") is None
    assert dexpools._to_float("inf") is None
    assert dexpools._to_float("-inf") is None
    assert dexpools._to_float("1.5") == 1.5


def test_orient_snapshot_target_as_base():
    pair = _pairs_by_chain()["ethereum"]["0x3416cf6c708da44db2624d63ea0aaef7113527c6"]
    snap = dexpools.orient_snapshot(pair, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
    assert snap["price_usd"] == pytest.approx(1.00049)
    assert snap["price_in_counterparty"] == pytest.approx(1.0004972)
    assert snap["liquidity_usd"] == pytest.approx(19735677.8)
    # CMC quotes serve no per-side pooled amounts; merge_pooled fills them.
    assert snap["pooled_target"] is None
    assert snap["pooled_counterparty"] is None
    assert snap["counterparty"] == {
        "symbol": "USDT", "address": "0xdac17f958d2ee523a2206206994597c13d831ec7"}
    assert snap["volume_h24"] == pytest.approx(12623670.66)
    assert snap["raw"] is pair


def test_orient_snapshot_target_as_quote_inverts_prices():
    pair = _pairs_by_chain()["ethereum"]["0xaaaa000000000000000000000000000000000001"]
    snap = dexpools.orient_snapshot(pair, "0x6b175474e89094c44da98b954eedeac495271d0f")
    # price_by_quote_asset = USDT in DAI = 0.999; DAI in USDT = 1/0.999.
    assert snap["price_in_counterparty"] == pytest.approx(1 / 0.999)
    # DAI price_usd = price(base USDT, USD) / price_by_quote_asset = 0.9991 / 0.999.
    assert snap["price_usd"] == pytest.approx(0.9991 / 0.999)
    assert snap["counterparty"]["symbol"] == "USDT"


def test_orient_snapshot_token_matching_neither_side_is_none():
    pair = _pairs_by_chain()["ethereum"]["0x3416cf6c708da44db2624d63ea0aaef7113527c6"]
    assert dexpools.orient_snapshot(pair, "0xdeadbeef") is None


def _ds_pairs_by_chain():
    pairs = load_fixture("dexscreener_pairs_sample.json")["pairs"]
    return {"ethereum": {pair["pairAddress"].lower(): pair for pair in pairs}}


def test_merge_pooled_fills_amounts_from_dexscreener_pair():
    ds_pair = _ds_pairs_by_chain()["ethereum"][
        "0x3416cf6c708da44db2624d63ea0aaef7113527c6"]
    snapshot = {"pooled_target": None, "pooled_counterparty": None}
    out = dexpools.merge_pooled(
        snapshot, ds_pair, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
    assert out["pooled_target"] == 3008666        # liquidity.base (USDC)
    assert out["pooled_counterparty"] == 16725515  # liquidity.quote (USDT)


def test_merge_pooled_target_on_quote_side_swaps():
    ds_pair = _ds_pairs_by_chain()["ethereum"][
        "0xaaaa000000000000000000000000000000000001"]
    snapshot = {"pooled_target": None, "pooled_counterparty": None}
    out = dexpools.merge_pooled(
        snapshot, ds_pair, "0x6b175474e89094c44da98b954eedeac495271d0f")
    assert out["pooled_target"] == 2502500        # liquidity.quote (DAI)
    assert out["pooled_counterparty"] == 2500000  # liquidity.base (USDT)


def test_merge_pooled_tolerates_missing_inputs():
    ds_pair = _ds_pairs_by_chain()["ethereum"][
        "0x3416cf6c708da44db2624d63ea0aaef7113527c6"]
    assert dexpools.merge_pooled(None, ds_pair, "0x") is None
    snapshot = {"pooled_target": None, "pooled_counterparty": None}
    assert dexpools.merge_pooled(snapshot, None, "0x") is snapshot
    assert snapshot["pooled_target"] is None


def _token_pairs():
    return load_fixture("dexscreener_token_pairs_sample.json")


def test_snapshot_from_dexscreener_target_as_base():
    pair = _token_pairs()[0]  # USD0/USDC, USD0 is base
    snap = dexpools.snapshot_from_dexscreener(
        pair, "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5")
    assert snap["source"] == "dexscreener"
    assert snap["price_usd"] == 1.0
    assert snap["liquidity_usd"] == 1979006.0
    assert snap["volume_h24"] == 1000000.0
    assert snap["pooled_target"] == 744330          # liquidity.base
    assert snap["pooled_counterparty"] == 1235141   # liquidity.quote
    assert snap["counterparty"] == {
        "symbol": "USDC", "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"}


def test_snapshot_from_dexscreener_target_as_quote_swaps_pooled():
    pair = _token_pairs()[3]  # USDT/USD0, USD0 is quote
    snap = dexpools.snapshot_from_dexscreener(
        pair, "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5")
    assert snap["counterparty"]["symbol"] == "USDT"
    assert snap["pooled_target"] == 424921          # liquidity.quote (USD0)
    assert snap["pooled_counterparty"] == 191229    # liquidity.base (USDT)


def test_snapshot_from_dexscreener_token_matching_neither_side_is_none():
    assert dexpools.snapshot_from_dexscreener(_token_pairs()[0], "0xdeadbeef") is None


def _ds_token_pairs_by_chain():
    pairs = _token_pairs()
    return {"ethereum": {p["pairAddress"].lower(): p for p in pairs}}


def test_build_snapshot_prefers_cmc_and_fills_pooled_from_dexscreener():
    # CMC indexes the USDC/USDT pool; pooled amounts come from the DS pair.
    job = {"chain": "ethereum",
           "pool_address": "0x3416cf6c708da44db2624d63ea0aaef7113527c6",
           "token_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"}
    ds_by_chain = {"ethereum": {
        "0x3416cf6c708da44db2624d63ea0aaef7113527c6":
            _ds_pairs_by_chain()["ethereum"][
                "0x3416cf6c708da44db2624d63ea0aaef7113527c6"]}}
    snap = dexpools.build_snapshot(job, _pairs_by_chain(), ds_by_chain)
    assert snap["source"] == "cmc"
    assert snap["liquidity_usd"] == pytest.approx(19735677.8)  # CMC value
    assert snap["pooled_counterparty"] == 16725515            # DS value


def test_build_snapshot_falls_back_to_dexscreener_when_cmc_missing():
    job = {"chain": "ethereum",
           "pool_address": "0xcccc000000000000000000000000000000000001",
           "token_address": "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5"}
    snap = dexpools.build_snapshot(job, {"ethereum": {}}, _ds_token_pairs_by_chain())
    assert snap["source"] == "dexscreener"
    assert snap["liquidity_usd"] == 1979006.0
    assert snap["pooled_counterparty"] == 1235141


def test_build_snapshot_none_when_both_sources_missing():
    job = {"chain": "ethereum", "pool_address": "0xdead", "token_address": "0xbeef"}
    assert dexpools.build_snapshot(job, {"ethereum": {}}, {"ethereum": {}}) is None


def _disc_jobs():
    # Two USD0 pools (same target) + one USDC pool (separate target).
    return [
        {"symbol": "USD0", "chain": "ethereum", "dex": "uniswap",
         "pool_address": "0xpool1", "token_address": USD0,
         "network": "ethereum", "gecko_network": "eth"},
        {"symbol": "USD0", "chain": "ethereum", "dex": "curve",
         "pool_address": "0xpool2", "token_address": USD0,
         "network": "ethereum", "gecko_network": "eth"},
        {"symbol": "USDC", "chain": "ethereum", "dex": "uniswap",
         "pool_address": "0xpool3", "token_address": USDC_ADDR,
         "network": "ethereum", "gecko_network": "eth"},
    ]


def test_assemble_groups_persists_selection_and_drops_unscored():
    jobs = _disc_jobs()
    snapshots = {
        ("ethereum", "0xpool1", USD0): {"liquidity_usd": 2000000.0, "source": "cmc"},
        ("ethereum", "0xpool2", USD0): {"liquidity_usd": 600000.0, "source": "dexscreener"},
        ("ethereum", "0xpool3", USDC_ADDR): None,  # no snapshot -> unscorable -> dropped
    }
    payload = dexpools.assemble(
        jobs, snapshots, history_days=180, fetched_at="2026-06-16T00:00:00Z",
        history_selected={("ethereum", "0xpool1", USD0)}, min_pool_liquidity=50000)
    assert payload["counts"] == {
        "target_tokens": 2, "qualifying_pools": 3, "snapshot_ok": 2,
        "persisted_pools": 2, "dropped_unscored": 1}
    # pool3 (USDC, no snapshot, not selected) is dropped, so only USD0 remains.
    assert [c["symbol"] for c in payload["stablecoins"]] == ["USD0"]
    pools = payload["stablecoins"][0]["pools"]
    assert [p["pool_address"] for p in pools] == ["0xpool1", "0xpool2"]
    assert pools[0]["gecko_network"] == "eth"
    assert "ohlcv_daily" not in pools[0] and "ohlcv_minute" not in pools[0]
    assert pools[0]["flags"] == {"history_selected": True}
    assert pools[1]["flags"] == {"history_selected": False}
    json.dumps(payload)  # must be JSON-serialisable


def test_assemble_keeps_subthreshold_pool_only_when_history_selected():
    # A pool below the liquidity floor is kept iff it is the per-target history
    # pool (depeg/dynamic reference); otherwise it feeds no factor and is dropped.
    jobs = [
        {"symbol": "USD0", "chain": "ethereum", "dex": "a", "pool_address": "0xbig",
         "token_address": USD0, "network": "ethereum", "gecko_network": "eth"},
        {"symbol": "USD0", "chain": "ethereum", "dex": "b", "pool_address": "0xtinysel",
         "token_address": USD0, "network": "ethereum", "gecko_network": "eth"},
        {"symbol": "USD0", "chain": "ethereum", "dex": "c", "pool_address": "0xtinydead",
         "token_address": USD0, "network": "ethereum", "gecko_network": "eth"},
    ]
    snapshots = {
        ("ethereum", "0xbig", USD0): {"liquidity_usd": 80000.0},      # >= floor -> kept
        ("ethereum", "0xtinysel", USD0): {"liquidity_usd": 9000.0},   # < floor but selected
        ("ethereum", "0xtinydead", USD0): {"liquidity_usd": 9000.0},  # < floor, unselected
    }
    payload = dexpools.assemble(
        jobs, snapshots, history_days=180, fetched_at="t",
        history_selected={("ethereum", "0xtinysel", USD0)}, min_pool_liquidity=50000)
    kept = {p["pool_address"] for p in payload["stablecoins"][0]["pools"]}
    assert kept == {"0xbig", "0xtinysel"}
    assert payload["counts"]["persisted_pools"] == 2
    assert payload["counts"]["dropped_unscored"] == 1


def test_assemble_default_floor_keeps_every_snapshotted_pool():
    # Default min_pool_liquidity=0: any pool with a snapshot is kept; only pools
    # without a snapshot (and not selected) are dropped.
    jobs = _disc_jobs()
    snapshots = {
        ("ethereum", "0xpool1", USD0): {"liquidity_usd": 100.0},
        ("ethereum", "0xpool2", USD0): {"liquidity_usd": 0.0},
        ("ethereum", "0xpool3", USDC_ADDR): None,
    }
    payload = dexpools.assemble(
        jobs, snapshots, history_days=180, fetched_at="t")
    assert payload["counts"]["persisted_pools"] == 2  # pool1, pool2 kept; pool3 dropped
    assert payload["counts"]["dropped_unscored"] == 1
