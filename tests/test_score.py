import json
import pathlib

import pytest

import score

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def vault_payload():
    return load_fixture("vault_cache_sample.json")


@pytest.fixture
def dex_payload():
    return load_fixture("dex_pools_sample.json")


def load_config():
    return json.loads(pathlib.Path(score.DEFAULT_CONFIG).read_text())


def test_default_paths_anchor_on_the_skills_tree():
    assert pathlib.Path(score.DEFAULT_CONFIG).is_file()
    assert pathlib.Path(score.DEFAULT_STATIC).is_file()
    assert pathlib.Path(score.DEFAULT_VAULTS).name == "defillama_yields.json"
    assert pathlib.Path(score.DEFAULT_DEX).name == "dex_pools.json"
    assert pathlib.Path(score.DEFAULT_HISTORY).name == "ohlcv_history.json"
    assert pathlib.Path(score.DEFAULT_OUT).name == "vault_scores.json"


def test_build_payload_shape_and_ordering(vault_payload, dex_payload):
    payload = score.build_payload(
        vault_payload, dex_payload, load_config(),
        generated_at="2026-06-15T01:00:00Z",
        vaults_path="vaults.json", dex_path="dex.json")
    assert set(payload) == {"source", "generated_at", "model", "inputs",
                            "counts", "scores"}
    assert payload["source"] == "versusos_score"
    assert payload["counts"]["vaults_scored"] == 5
    assert payload["counts"]["vaults_with_dex_data"] == 2     # v1, v2
    assert "vaults_with_audit_data" not in payload["counts"]

    assert payload["counts"]["vaults_with_history"] == 0   # no history cache passed

    scores = payload["scores"]
    # Ranking is on the uniform normalized_score; final_safety_score only breaks
    # ties (here all-initial, so normalized == final and both are descending).
    norms = [s["normalized_score"] for s in scores]
    assert norms == sorted(norms, reverse=True)
    finals = [s["final_safety_score"] for s in scores]
    assert finals == sorted(finals, reverse=True)
    record = next(s for s in scores if s["pool"] == "v1")
    assert {"pool", "project", "chain", "symbol", "tvlUsd", "apyBase", "apy",
            "evaluated_token", "raw_safety_score", "exploit_count",
            "exploit_penalty", "final_safety_score", "grade", "factors", "flags",
            "dex_pools_matched"} <= set(record)
    assert {"score_1", "score_2", "basis", "max_scale", "normalized_score",
            "final_safety_score"} <= set(record)
    assert record["dex_pools_matched"] == 2
    assert record["factors"]["vault_tvl"] == 20    # tvlUsd 25M -> 20
    assert record["evaluated_token"] == "USDC"
    assert 0 <= record["final_safety_score"] <= 100   # initial (no history passed)
    assert record["grade"] in {"Safe", "Moderate", "Aggressive", "High Risk", "Avoid"}


def test_rank_key_orders_by_normalized_then_final():
    """Safety ranking is on the uniform normalized_score, not the scale-variant
    final_safety_score: a deep vault with a higher final (0-200) but lower
    normalized must rank BELOW an initial vault with a higher normalized.
    final_safety_score only breaks ties (deeper-analyzed vault wins equal safety)."""
    initial = {"normalized_score": 72.73, "final_safety_score": 72.73}
    deep_lower = {"normalized_score": 42.0, "final_safety_score": 84.0}
    assert sorted([deep_lower, initial], key=score.rank_key,
                  reverse=True) == [initial, deep_lower]   # old final-sort inverted this
    tie_initial = {"normalized_score": 70.0, "final_safety_score": 70.0}
    tie_deep = {"normalized_score": 70.0, "final_safety_score": 140.0}
    assert sorted([tie_initial, tie_deep], key=score.rank_key,
                  reverse=True) == [tie_deep, tie_initial]


def test_build_payload_unmatched_vault_has_zero_dex_factors(vault_payload, dex_payload):
    payload = score.build_payload(
        vault_payload, dex_payload, load_config(),
        generated_at="2026-06-15T01:00:00Z",
        vaults_path="v.json", dex_path="d.json")
    unmatched = [r for r in payload["scores"] if r["dex_pools_matched"] == 0]
    assert {r["pool"] for r in unmatched} == {"v3", "v4", "v5"}
    for record in unmatched:
        assert record["factors"]["depeg"] == 0
        assert record["factors"]["pool_liquidity"] == 0
        assert record["factors"]["dynamic"] == {"points": 0, "stale": True}


def test_build_payload_deep_when_history_present(vault_payload, dex_payload):
    # ohlcv_history_sample.json's candle timestamps sit just inside the dynamic
    # 12h window relative to dex_pools_sample.json's fetched_at (2026-06-10), so
    # minute data counts and the matched vault reaches basis == "deep".
    history = load_fixture("ohlcv_history_sample.json")
    payload = score.build_payload(
        vault_payload, dex_payload, load_config(),
        generated_at="2026-06-15T01:00:00Z", vaults_path="v", dex_path="d",
        history_payload=history)
    assert payload["counts"]["vaults_with_history"] >= 1
    deep = [r for r in payload["scores"] if r["basis"] == "deep"]
    assert deep and all(r["max_scale"] == 200 for r in deep)


def test_main_end_to_end(tmp_path):
    out = tmp_path / "vault_scores.json"
    assert score.main(["--vaults", str(FIXTURES / "vault_cache_sample.json"),
                       "--dex", str(FIXTURES / "dex_pools_sample.json"),
                       "--history", str(tmp_path / "absent_history.json"),
                       "--out", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["counts"]["vaults_scored"] == 5
    assert all(s["max_scale"] in (100, 200) for s in payload["scores"])


def test_main_fails_without_dex_cache(tmp_path, capsys):
    out = tmp_path / "vault_scores.json"
    assert score.main(["--vaults", str(FIXTURES / "vault_cache_sample.json"),
                       "--dex", str(tmp_path / "absent.json"),
                       "--out", str(out)]) == 1
    assert not out.exists()
    assert "collect-dex" in capsys.readouterr().err


def test_main_fails_without_vault_cache(tmp_path, capsys):
    out = tmp_path / "vault_scores.json"
    assert score.main(["--vaults", str(tmp_path / "absent.json"),
                       "--out", str(out)]) == 1
    assert not out.exists()
    assert "collect-vault" in capsys.readouterr().err


def test_main_rejects_unknown_flag(tmp_path):
    with pytest.raises(SystemExit):
        score.main(["--vaults", str(FIXTURES / "vault_cache_sample.json"),
                    "--out", str(tmp_path / "vault_scores.json"),
                    "--seed", "7"])
