import importlib.util
import json
import pathlib

SCRIPTS = (pathlib.Path(__file__).resolve().parents[1]
           / "skills" / "collect-depeg-history" / "scripts")
_spec = importlib.util.spec_from_file_location("depeg_collect", SCRIPTS / "collect.py")
depeg_collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(depeg_collect)


POOL = "0x" + "a" * 40  # a valid contract address (GeckoTerminal-fetchable)


def _dex():
    return {"stablecoins": [{"symbol": "USDC", "pools": [
        {"chain": "ethereum", "pool_address": POOL, "token_address": "0xusdc",
         "gecko_network": "eth", "flags": {"history_selected": True}}]}]}


def _scores():
    return {"scores": [{"pool": "v1", "symbol": "USDC", "chain": "ethereum"}]}


def test_defaults_anchored_to_skill_folder():
    assert depeg_collect.DEFAULT_CONFIG.endswith("config/collect.json")
    assert depeg_collect.DEFAULT_OUT.endswith("data/ohlcv_history.json")
    assert depeg_collect.DEFAULT_SCORES.endswith("vault_scores.json")
    assert depeg_collect.DEFAULT_DEX.endswith("dex_pools.json")
    assert pathlib.Path(depeg_collect.DEFAULT_CONFIG).is_file()


def test_collect_throttles_and_assembles(tmp_path, capsys):
    sleeps = []
    calls = []

    def fake_daily(network, address, *, days, token_address, **_):
        calls.append(("day", address))
        return [[1, 1.0, 1.0, 1.0, 1.0, 1.0]]

    def fake_minute(network, address, *, minutes, token_address, **_):
        calls.append(("min", address))
        return [[1, 1.0, 1.0, 0.99, 1.0, 1.0]]

    scores = tmp_path / "scores.json"; scores.write_text(json.dumps(_scores()))
    dex = tmp_path / "dex.json"; dex.write_text(json.dumps(_dex()))
    out = tmp_path / "ohlcv_history.json"
    code = depeg_collect.main(
        ["--scores", str(scores), "--dex", str(dex), "--out", str(out),
         "--config", depeg_collect.DEFAULT_CONFIG, "--top-n", "1"],
        fetch_daily=fake_daily, fetch_minute=fake_minute, sleep=sleeps.append)
    assert code == 0
    payload = json.loads(out.read_text())
    entry = payload["by_pool"][f"ethereum|{POOL}|0xusdc"]
    assert entry["ohlcv_daily"] and entry["ohlcv_minute"]
    assert payload["counts"] == {"targets": 1, "daily_ok": 1, "minute_ok": 1,
                                 "skipped_non_address": 0}
    assert ("day", POOL) in calls and ("min", POOL) in calls
    # Throttle is per call: the minute call waits one throttle behind the daily one
    # (the daily call is the very first, so it does not wait) — no back-to-back burst.
    throttle = depeg_collect.load_json(depeg_collect.DEFAULT_CONFIG)["throttle_seconds"]
    assert sleeps == [throttle]


def test_collect_skips_non_address_pools(capsys):
    # Uni-v4 pool ids (0x + 64 hex) and Curve composites are not GeckoTerminal-
    # fetchable; they are skipped (no fetch) instead of 404ing.
    real = "0x" + "a" * 40
    targets_list = [
        {"chain": "ethereum", "pool_address": real, "token_address": "0xt",
         "gecko_network": "eth", "symbol": "USDC"},
        {"chain": "ethereum", "pool_address": "0x" + "b" * 64, "token_address": "0xt",
         "gecko_network": "eth", "symbol": "USDC"},
        {"chain": "ethereum", "pool_address": "0xaaa-0xbbb", "token_address": "0xt",
         "gecko_network": "eth", "symbol": "USDC"},
    ]
    calls = []

    def fake_daily(network, address, *, days, token_address, **_):
        calls.append(("day", address)); return [[1, 1, 1, 1, 1, 1]]

    def fake_minute(network, address, *, minutes, token_address, **_):
        calls.append(("min", address)); return [[1, 1, 1, 0.99, 1, 1]]

    options = {"minute_window_hours": 12, "throttle_seconds": 0, "history_days": 180}
    out = depeg_collect.collect(
        targets_list, options, fetch_daily=fake_daily, fetch_minute=fake_minute,
        sleep=lambda s: None)
    # Only the real address is fetched (daily + minute).
    assert calls == [("day", real), ("min", real)]
    assert out["counts"] == {"targets": 3, "daily_ok": 1, "minute_ok": 1,
                             "skipped_non_address": 2}
    # Skipped pools are still recorded with null OHLCV.
    assert out["by_pool"]["ethereum|0x" + "b" * 64 + "|0xt"]["ohlcv_daily"] is None
    assert "not a GeckoTerminal-fetchable" in capsys.readouterr().err


def test_collect_exits_one_when_no_targets(tmp_path, capsys):
    scores = tmp_path / "s.json"; scores.write_text(json.dumps({"scores": []}))
    dex = tmp_path / "d.json"; dex.write_text(json.dumps({"stablecoins": []}))
    code = depeg_collect.main(
        ["--scores", str(scores), "--dex", str(dex),
         "--out", str(tmp_path / "o.json"), "--config", depeg_collect.DEFAULT_CONFIG])
    assert code == 1
    assert "no targets" in capsys.readouterr().err


def test_collect_exits_one_when_cache_missing(tmp_path, capsys):
    code = depeg_collect.main(
        ["--scores", str(tmp_path / "missing.json"),
         "--dex", str(tmp_path / "also-missing.json"),
         "--out", str(tmp_path / "o.json"),
         "--config", depeg_collect.DEFAULT_CONFIG])
    assert code == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_collect_exits_one_when_all_fetches_fail(tmp_path, capsys):
    def boom(*a, **k):
        raise RuntimeError("429 boom")
    scores = tmp_path / "s.json"; scores.write_text(json.dumps(_scores()))
    dex = tmp_path / "d.json"; dex.write_text(json.dumps(_dex()))
    out = tmp_path / "o.json"
    code = depeg_collect.main(
        ["--scores", str(scores), "--dex", str(dex), "--out", str(out),
         "--config", depeg_collect.DEFAULT_CONFIG, "--top-n", "1"],
        fetch_daily=boom, fetch_minute=boom, sleep=lambda s: None)
    assert code == 1
    assert not out.exists()


REAL_A = "0x" + "a" * 40
REAL_B = "0x" + "b" * 40


def _fixed_daily(*_a, **_k):
    return [[1, 1.0, 1.0, 1.0, 1.0, 1.0]]


def _fixed_minute(*_a, **_k):
    return [[1, 1.0, 1.0, 0.99, 1.0, 1.0]]


def test_collect_throttles_before_every_call():
    # Two pools => 4 calls (day,min × 2). The per-call throttle pauses before
    # every call except the very first, so daily+minute never burst together.
    targets_list = [
        {"chain": "ethereum", "pool_address": REAL_A, "token_address": "0xt",
         "gecko_network": "eth", "symbol": "USDC"},
        {"chain": "ethereum", "pool_address": REAL_B, "token_address": "0xt",
         "gecko_network": "eth", "symbol": "USDT"},
    ]
    sleeps = []
    options = {"minute_window_hours": 12, "throttle_seconds": 6.0, "history_days": 180}
    depeg_collect.collect(targets_list, options, fetch_daily=_fixed_daily,
                          fetch_minute=_fixed_minute, sleep=sleeps.append)
    assert sleeps == [6.0, 6.0, 6.0]


def test_collect_reuses_cached_pool_without_fetching():
    # A pool already fully collected is reused, not re-fetched — the core of the
    # resume behaviour that keeps QA re-runs under the rate limit.
    key = f"ethereum|{REAL_A}|0xt"
    existing = {key: {"chain": "ethereum", "pool_address": REAL_A,
                      "token_address": "0xt", "ohlcv_daily": _fixed_daily(),
                      "ohlcv_minute": _fixed_minute()}}
    targets_list = [{"chain": "ethereum", "pool_address": REAL_A, "token_address": "0xt",
                     "gecko_network": "eth", "symbol": "USDC"}]
    events = []

    def boom(*_a, **_k):
        raise AssertionError("a fully-cached pool must not be fetched")

    out = depeg_collect.collect(
        targets_list, {"minute_window_hours": 12, "throttle_seconds": 6.0,
                       "history_days": 180},
        existing=existing, fetch_daily=boom, fetch_minute=boom, sleep=events.append)
    assert events == []  # nothing fetched, nothing slept
    assert out["by_pool"][key]["ohlcv_daily"] == _fixed_daily()
    assert out["counts"] == {"targets": 1, "daily_ok": 1, "minute_ok": 1,
                             "skipped_non_address": 0}


def test_collect_fills_only_missing_piece():
    # daily already cached, minute missing => only the minute call is made.
    key = f"ethereum|{REAL_A}|0xt"
    existing = {key: {"chain": "ethereum", "pool_address": REAL_A,
                      "token_address": "0xt", "ohlcv_daily": _fixed_daily(),
                      "ohlcv_minute": None}}
    targets_list = [{"chain": "ethereum", "pool_address": REAL_A, "token_address": "0xt",
                     "gecko_network": "eth", "symbol": "USDC"}]
    calls = []

    def fake_daily(*_a, **_k):
        calls.append("day"); return [[2, 2, 2, 2, 2, 2]]

    def fake_minute(*_a, **_k):
        calls.append("min"); return _fixed_minute()

    out = depeg_collect.collect(
        targets_list, {"minute_window_hours": 12, "throttle_seconds": 0,
                       "history_days": 180},
        existing=existing, fetch_daily=fake_daily, fetch_minute=fake_minute,
        sleep=lambda s: None)
    assert calls == ["min"]  # daily reused, only the gap fetched
    assert out["by_pool"][key]["ohlcv_daily"] == _fixed_daily()  # untouched
    assert out["by_pool"][key]["ohlcv_minute"] == _fixed_minute()


def test_collect_refresh_refetches_all():
    key = f"ethereum|{REAL_A}|0xt"
    existing = {key: {"chain": "ethereum", "pool_address": REAL_A,
                      "token_address": "0xt", "ohlcv_daily": _fixed_daily(),
                      "ohlcv_minute": _fixed_minute()}}
    targets_list = [{"chain": "ethereum", "pool_address": REAL_A, "token_address": "0xt",
                     "gecko_network": "eth", "symbol": "USDC"}]
    calls = []

    def fake_daily(*_a, **_k):
        calls.append("day"); return [[9, 9, 9, 9, 9, 9]]

    def fake_minute(*_a, **_k):
        calls.append("min"); return [[9, 9, 9, 9, 9, 9]]

    out = depeg_collect.collect(
        targets_list, {"minute_window_hours": 12, "throttle_seconds": 0,
                       "history_days": 180},
        existing=existing, refresh=True, fetch_daily=fake_daily,
        fetch_minute=fake_minute, sleep=lambda s: None)
    assert calls == ["day", "min"]
    assert out["by_pool"][key]["ohlcv_daily"] == [[9, 9, 9, 9, 9, 9]]


def test_collect_preserves_pools_outside_targets():
    # A previously-collected pool survives even when it is no longer a target,
    # so a smaller-top-N (or partly-failed) re-run never regresses the cache.
    key_cached = f"ethereum|{REAL_A}|0xt"
    existing = {key_cached: {"chain": "ethereum", "pool_address": REAL_A,
                             "token_address": "0xt", "ohlcv_daily": _fixed_daily(),
                             "ohlcv_minute": _fixed_minute()}}
    targets_list = [{"chain": "ethereum", "pool_address": REAL_B, "token_address": "0xt",
                     "gecko_network": "eth", "symbol": "USDT"}]
    out = depeg_collect.collect(
        targets_list, {"minute_window_hours": 12, "throttle_seconds": 0,
                       "history_days": 180},
        existing=existing, fetch_daily=_fixed_daily, fetch_minute=_fixed_minute,
        sleep=lambda s: None)
    assert key_cached in out["by_pool"]  # untouched survivor
    assert out["by_pool"][key_cached]["ohlcv_daily"] == _fixed_daily()
    assert f"ethereum|{REAL_B}|0xt" in out["by_pool"]  # newly collected
