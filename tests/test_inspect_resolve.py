import json
import pathlib

import resolve

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
USDC = "0xA0b86991c6218b36C1D19D4a2e9Eb0cE3606eB48"
YIELDS = str(FIXTURES / "inspect_yields_sample.json")
SCORES = str(FIXTURES / "inspect_scores_sample.json")


def test_default_paths_anchor_on_the_skills_tree():
    assert pathlib.Path(resolve.DEFAULT_VAULTS).name == "defillama_yields.json"
    assert pathlib.Path(resolve.DEFAULT_SCORES).name == "vault_scores.json"


def test_main_prints_matches_json(capsys):
    assert resolve.main(["--addresses", USDC, "--vaults", YIELDS, "--scores", SCORES]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 3
    assert [m["pool"] for m in out["matches"]] == ["v2", "v3", "v5"]
    assert out["query"]["addresses"] == [USDC.lower()]


def test_main_chain_filter(capsys):
    resolve.main(["--addresses", USDC, "--chain", "ethereum", "--vaults", YIELDS, "--scores", SCORES])
    out = json.loads(capsys.readouterr().out)
    assert [m["pool"] for m in out["matches"]] == ["v2", "v3"]


def test_main_no_match_is_zero_count(capsys):
    resolve.main(["--addresses", "0x" + "de" * 20, "--vaults", YIELDS, "--scores", SCORES])
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 0 and out["matches"] == []


def test_main_fails_without_score_cache(tmp_path, capsys):
    assert resolve.main(["--addresses", USDC, "--vaults", YIELDS,
                         "--scores", str(tmp_path / "absent.json")]) == 1
    assert "Score cache not found" in capsys.readouterr().err


def test_main_fails_without_vault_cache(tmp_path, capsys):
    assert resolve.main(["--addresses", USDC, "--vaults", str(tmp_path / "absent.json"),
                         "--scores", SCORES]) == 1
    assert "Vault cache not found" in capsys.readouterr().err


SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_main_rejects_non_evm_address(capsys):
    assert resolve.main(["--addresses", SOLANA, "--vaults", YIELDS, "--scores", SCORES]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 0 and out["matches"] == []
    assert out["rejected_non_evm"] == [SOLANA]


def test_main_keeps_evm_and_rejects_non_evm_together(capsys):
    resolve.main(["--addresses", USDC, SOLANA, "--vaults", YIELDS, "--scores", SCORES])
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 3
    assert out["rejected_non_evm"] == [SOLANA]
