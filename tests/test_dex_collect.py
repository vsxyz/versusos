import importlib.util
import json
import pathlib

SCRIPTS = (pathlib.Path(__file__).resolve().parents[1]
           / "skills" / "collect-dex" / "scripts")
_spec = importlib.util.spec_from_file_location("dex_collect", SCRIPTS / "collect.py")
dex_collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dex_collect)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
USD0 = "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_defaults_are_anchored_to_the_skill_folder():
    assert dex_collect.DEFAULT_VAULTS.endswith("defillama_yields.json")
    assert dex_collect.DEFAULT_CONFIG.endswith("config/collect.json")
    assert dex_collect.DEFAULT_OUT.endswith("data/dex_pools.json")
    assert pathlib.Path(dex_collect.DEFAULT_CONFIG).is_file()
    assert not hasattr(dex_collect, "DEFAULT_MAPPING")


def test_collect_discovery_filters_and_indexes(capsys):
    seeds = [{"chain": "ethereum", "token_address": USD0,
              "network": "ethereum", "gecko_network": "eth"}]
    pairs = load_fixture("dexscreener_token_pairs_sample.json")

    def fake_fetch(chain, token, **_):
        assert (chain, token) == ("ethereum", USD0)
        return pairs

    jobs, ds = dex_collect.collect_discovery(
        seeds, {"ethereum": {USDC, USDT}}, fetch_token_pools=fake_fetch)
    assert len(jobs) == 3  # bUSD0 counterparty dropped
    assert set(ds["ethereum"]) == {
        "0xcccc000000000000000000000000000000000001",
        "0xcccc000000000000000000000000000000000002",
        "0xcccc000000000000000000000000000000000004"}


def test_collect_discovery_survives_seed_failure(capsys):
    seeds = [{"chain": "ethereum", "token_address": USD0,
              "network": "ethereum", "gecko_network": "eth"}]

    def fake_fetch(chain, token, **_):
        raise RuntimeError("boom")

    jobs, ds = dex_collect.collect_discovery(
        seeds, {"ethereum": {USDC}}, fetch_token_pools=fake_fetch)
    assert jobs == [] and ds == {}
    assert "discovery failed" in capsys.readouterr().err


def _snap_jobs(addresses):
    return [{"chain": "ethereum", "network": "ethereum", "pool_address": a}
            for a in addresses]


def test_collect_snapshots_filters_invalid_addresses_and_chunks():
    valid = ["0x%040d" % i for i in range(5)]
    bad_hash = "0x" + "a" * 64                  # 32-byte pool id
    bad_composite = valid[0] + "-" + valid[1]   # Curve composite
    jobs = _snap_jobs(valid + [bad_hash, bad_composite])
    calls = []

    def fake_fetch(network, addresses, *, api_key):
        calls.append((network, list(addresses)))
        return {a.lower(): {"addr": a} for a in addresses}

    out = dex_collect.collect_snapshots(
        jobs, "k", fetch_pairs=fake_fetch, batch_size=2)
    # Invalid addresses are never sent; 5 valid -> chunks of 2, 2, 1.
    assert [len(addrs) for _, addrs in calls] == [2, 2, 1]
    sent = [a for _, addrs in calls for a in addrs]
    assert sent == valid
    assert bad_hash not in sent and bad_composite not in sent
    assert set(out["ethereum"]) == {a.lower() for a in valid}


def test_collect_snapshots_isolates_a_failed_chunk(capsys):
    valid = ["0x%040d" % i for i in range(3)]

    def fake_fetch(network, addresses, *, api_key):
        if addresses[0] == valid[0]:
            raise RuntimeError("HTTP Error 414: Request-URI Too Large")
        return {a.lower(): {"ok": True} for a in addresses}

    # batch_size=1 -> 3 chunks; the first fails, the rest still return.
    out = dex_collect.collect_snapshots(
        _snap_jobs(valid), "k", fetch_pairs=fake_fetch, batch_size=1)
    assert set(out["ethereum"]) == {valid[1].lower(), valid[2].lower()}
    assert "snapshot fetch failed" in capsys.readouterr().err


def test_collect_snapshots_skips_cmc_unsupported_networks(capsys):
    # CMC's DEX API 400s "network is not supported" for bsc/avalanche; those
    # never reach CMC — they fall back to the Dexscreener snapshot downstream.
    jobs = [{"chain": "ethereum", "network": "ethereum", "pool_address": "0x%040d" % 1},
            {"chain": "bsc", "network": "bsc", "pool_address": "0x%040d" % 2}]
    calls = []

    def fake_fetch(network, addresses, *, api_key):
        calls.append(network)
        return {a.lower(): {} for a in addresses}

    out = dex_collect.collect_snapshots(
        jobs, "k", fetch_pairs=fake_fetch,
        cmc_networks=["ethereum", "base", "arbitrum", "optimism", "polygon"])
    assert calls == ["ethereum"]   # bsc is never attempted
    assert out["bsc"] == {}        # -> Dexscreener fallback in build_snapshot
    assert "not served by the CMC" in capsys.readouterr().err


def _patch_pipeline(monkeypatch):
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    pairs = load_fixture("cmc_pair_quotes_sample.json")["data"]
    cmc_by_chain = {"ethereum": {p["contract_address"].lower(): p for p in pairs}}
    monkeypatch.setattr(dex_collect, "collect_snapshots",
                        lambda jobs, api_key, **_: cmc_by_chain)


def test_main_writes_cache_and_exits_zero(monkeypatch, tmp_path, capsys):
    _patch_pipeline(monkeypatch)
    # discovery returns one job whose CMC snapshot exists in the fixture.
    usdc_pool = "0x3416cf6c708da44db2624d63ea0aaef7113527c6"
    monkeypatch.setattr(dex_collect, "collect_discovery",
                        lambda seeds, wl, **_: (
                            [{"symbol": "USDC", "chain": "ethereum", "dex": "uniswap-v3",
                              "pool_address": usdc_pool, "token_address": USDC,
                              "network": "ethereum", "gecko_network": "eth"}],
                            {"ethereum": {}}))
    out = tmp_path / "dex_pools.json"
    code = dex_collect.main([
        "--vaults", str(FIXTURES / "dex_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["source"] == "coinmarketcap-dex+dexscreener"
    assert payload["counts"]["qualifying_pools"] == 1
    assert payload["counts"]["snapshot_ok"] == 1
    assert payload["counts"]["persisted_pools"] == 1  # 19.7M liquidity >= floor
    assert payload["counts"]["dropped_unscored"] == 0
    assert "history-selected" in capsys.readouterr().out


def test_main_drops_subthreshold_pools_from_cache(monkeypatch, tmp_path):
    # Two USDC/USDT pools via the Dexscreener fallback: one above the floor (also
    # the per-target history pool), one below and unselected -> dropped from cache.
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    monkeypatch.setattr(dex_collect, "collect_snapshots",
                        lambda jobs, api_key, **_: {"ethereum": {}})  # force DS fallback

    def ds(addr, liq):
        return {"pairAddress": addr, "dexId": "uni",
                "baseToken": {"address": USDC, "symbol": "USDC"},
                "quoteToken": {"address": USDT, "symbol": "USDT"},
                "priceUsd": "1.0", "priceNative": "1.0",
                "liquidity": {"usd": liq, "base": 1, "quote": 1},
                "volume": {"h24": 1}}

    jobs = [{"symbol": "USDC", "chain": "ethereum", "dex": "uni",
             "pool_address": addr, "token_address": USDC,
             "network": "ethereum", "gecko_network": "eth"}
            for addr in ("0xbig", "0xsmall")]
    ds_by_chain = {"ethereum": {"0xbig": ds("0xbig", 80000.0),
                                "0xsmall": ds("0xsmall", 9000.0)}}
    monkeypatch.setattr(dex_collect, "collect_discovery",
                        lambda seeds, wl, **_: (jobs, ds_by_chain))
    out = tmp_path / "dex_pools.json"
    code = dex_collect.main([
        "--vaults", str(FIXTURES / "dex_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["counts"]["qualifying_pools"] == 2
    assert payload["counts"]["persisted_pools"] == 1
    assert payload["counts"]["dropped_unscored"] == 1
    kept = [p["pool_address"] for s in payload["stablecoins"] for p in s["pools"]]
    assert kept == ["0xbig"]


def test_main_exits_one_when_discovery_finds_nothing(monkeypatch, tmp_path, capsys):
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(dex_collect, "collect_discovery",
                        lambda seeds, wl, **_: ([], {}))
    out = tmp_path / "dex_pools.json"
    code = dex_collect.main([
        "--vaults", str(FIXTURES / "dex_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 1
    assert not out.exists()
    assert "no USDC/USDT-paired pools" in capsys.readouterr().err


def test_main_exits_one_when_vault_cache_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    out = tmp_path / "dex_pools.json"
    code = dex_collect.main([
        "--vaults", str(tmp_path / "missing.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 1
    assert "vault cache not found" in capsys.readouterr().err


def test_main_exits_one_without_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CMC_PRO_API_KEY", raising=False)
    monkeypatch.setattr(dex_collect, "KEY_FILE", tmp_path / "missing.env")
    out = tmp_path / "dex_pools.json"
    code = dex_collect.main([
        "--vaults", str(FIXTURES / "dex_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 1
    assert "CMC_PRO_API_KEY" in capsys.readouterr().err


def test_resolve_api_key_env_wins_over_file(monkeypatch, tmp_path):
    key_file = tmp_path / ".env"
    key_file.write_text("CMC_PRO_API_KEY=from-file\n")
    monkeypatch.setattr(dex_collect, "KEY_FILE", key_file)
    monkeypatch.setenv("CMC_PRO_API_KEY", "from-env")
    assert dex_collect.resolve_api_key() == "from-env"


def test_resolve_api_key_reads_dotenv_file(monkeypatch, tmp_path):
    key_file = tmp_path / ".env"
    key_file.write_text('# c\n\nOTHER=nope\nCMC_PRO_API_KEY="from-file"\n')
    monkeypatch.setattr(dex_collect, "KEY_FILE", key_file)
    monkeypatch.delenv("CMC_PRO_API_KEY", raising=False)
    assert dex_collect.resolve_api_key() == "from-file"


def test_bundled_config_has_whitelist_and_history_days():
    config = json.loads((SCRIPTS.parent / "config" / "collect.json").read_text())
    assert config["history_days"] == 180
    assert "ethereum" in config["counterparty_whitelist"]
    assert config["abnormal_price_delta"] == 0.5
    # Persist floor must match score's pool_liquidity.min_pool_tvl (score-neutral).
    assert config["min_pool_liquidity"] == 50000
    assert config["cmc_batch_size"] == 100  # CMC address-list chunk size (avoids 414)
    # CMC DEX serves these networks; bsc/avalanche are unsupported (DS fallback).
    assert "ethereum" in config["cmc_networks"]
    assert "bsc" not in config["cmc_networks"]
    assert "avalanche" not in config["cmc_networks"]
