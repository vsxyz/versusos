import json
import pathlib

from core import matching

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
USDC = "0xA0b86991c6218b36C1D19D4a2e9Eb0cE3606eB48"
USD0 = "0x73a15FED60bf67631dc6cd7Bc5B6e8da8190aCF5"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def vaults():
    return load("inspect_yields_sample.json")


def scores():
    return load("inspect_scores_sample.json")


def test_single_token_matches_all_evm_vaults_using_it():
    result = matching.match_token([USDC], vaults(), scores())
    assert [r["pool"] for r in result] == ["v2", "v3", "v5"]
    assert all(r["scored"] for r in result)


def test_results_are_safety_ranked_desc():
    result = matching.match_token([USDC], vaults(), scores())
    norms = [r["normalized_score"] for r in result]
    assert norms == sorted(norms, reverse=True)


def test_address_match_is_case_insensitive():
    result = matching.match_token([USDC.lower()], vaults(), scores())
    assert {r["pool"] for r in result} == {"v2", "v3", "v5"}


def test_chain_filter_scopes_to_one_chain():
    assert [r["pool"] for r in matching.match_token([USDC], vaults(), scores(), chain="ethereum")] == ["v2", "v3"]
    assert [r["pool"] for r in matching.match_token([USDC], vaults(), scores(), chain="base")] == ["v5"]


def test_matched_but_unscored_vault_is_flagged():
    result = matching.match_token([USD0], vaults(), scores())
    assert result == [{"pool": "v1", "project": "usual", "chain": "Ethereum",
                       "symbol": "USD0", "tvlUsd": 25000000, "scored": False}]


def test_no_match_returns_empty():
    assert matching.match_token(["0x" + "de" * 20], vaults(), scores()) == []


def test_empty_addresses_returns_empty():
    assert matching.match_token([], vaults(), scores()) == []


def test_results_tiebreak_by_tvl_desc_when_scores_equal():
    vaults = {"vaults": [
        {"pool": "a", "chain": "Ethereum", "underlyingTokens": [USDC]},
        {"pool": "b", "chain": "Ethereum", "underlyingTokens": [USDC]},
    ]}
    scores = {"scores": [
        {"pool": "a", "normalized_score": 70.0, "tvlUsd": 1000000},
        {"pool": "b", "normalized_score": 70.0, "tvlUsd": 9000000},
    ]}
    result = matching.match_token([USDC], vaults, scores)
    assert [r["pool"] for r in result] == ["b", "a"]   # equal score -> larger tvlUsd first


def test_is_evm_address():
    from core import matching
    assert matching.is_evm_address("0x" + "a" * 40) is True
    assert matching.is_evm_address("0X" + "A" * 40) is True
    assert matching.is_evm_address("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") is False
    assert matching.is_evm_address("0x1234") is False
    assert matching.is_evm_address(None) is False
