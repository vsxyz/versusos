import json
import pathlib

from core import filters

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_vault_token_symbols_splits_and_uppercases():
    assert filters.vault_token_symbols({"symbol": "USDC-USDT"}) == ["USDC", "USDT"]
    assert filters.vault_token_symbols({"symbol": "usdc"}) == ["USDC"]
    assert filters.vault_token_symbols({"symbol": ""}) == []
    assert filters.vault_token_symbols({}) == []


def test_build_allowed_symbols_expands_usd_group_and_adds_symbols():
    token_config = {"groups": ["ALL_USD_STABLES"], "symbols": ["EURC"]}
    usd = {"USDC", "USDT", "DAI"}
    assert filters.build_allowed_symbols(token_config, usd) == {"USDC", "USDT", "DAI", "EURC"}


def test_build_allowed_symbols_uppercases_explicit_symbols():
    assert filters.build_allowed_symbols({"symbols": ["eurc"]}, set()) == {"EURC"}


ALLOWED = {"USDC", "USDT", "DAI"}
EXAMPLE_FILTERS = {"min_tvl_usd": 1000000}


def _vault(vault_id):
    vaults = load_fixture("defillama_vaults_sample.json")["data"]
    return next(v for v in vaults if v["pool"] == vault_id)


def test_passes_filters_single_requires_allowed_token():
    assert filters.passes_filters(_vault("p1"), EXAMPLE_FILTERS, ALLOWED) is True   # USDC
    assert filters.passes_filters(_vault("p3"), EXAMPLE_FILTERS, ALLOWED) is False  # EURC not allowed


def test_passes_filters_rejects_pairs():
    assert filters.passes_filters(_vault("p5"), EXAMPLE_FILTERS, ALLOWED) is False   # USDC-USDT
    assert filters.passes_filters(_vault("p8"), EXAMPLE_FILTERS, ALLOWED) is False   # USDC-WETH
    assert filters.passes_filters(_vault("p10"), EXAMPLE_FILTERS, ALLOWED) is False  # USDT-DAI
    assert filters.passes_filters(_vault("p4"), EXAMPLE_FILTERS, ALLOWED) is False   # WETH-MSETH


def test_passes_filters_rejects_three_plus_tokens():
    assert filters.passes_filters(_vault("p9"), EXAMPLE_FILTERS, ALLOWED) is False  # DAI-USDC-USDT


def test_passes_filters_applies_min_tvl():
    assert filters.passes_filters(_vault("p6"), EXAMPLE_FILTERS, ALLOWED) is False  # tvl < 1M


def test_filter_vaults_keeps_only_passing_in_input_order():
    vaults = load_fixture("defillama_vaults_sample.json")["data"]
    result = filters.filter_vaults(vaults, EXAMPLE_FILTERS, ALLOWED)
    assert [v["pool"] for v in result] == ["p1", "p2", "p7"]


def test_sort_vaults_desc_puts_missing_field_last():
    vaults = filters.filter_vaults(
        load_fixture("defillama_vaults_sample.json")["data"], EXAMPLE_FILTERS, ALLOWED
    )
    result = filters.sort_vaults(vaults, "apyBase", desc=True)
    # p7 has apyBase=null and must sort last regardless of direction.
    assert [v["pool"] for v in result] == ["p2", "p1", "p7"]


def test_sort_vaults_asc_also_puts_missing_field_last():
    vaults = filters.filter_vaults(
        load_fixture("defillama_vaults_sample.json")["data"], EXAMPLE_FILTERS, ALLOWED
    )
    result = filters.sort_vaults(vaults, "apyBase", desc=False)
    assert [v["pool"] for v in result] == ["p1", "p2", "p7"]


EVM_FILTERS = {"min_tvl_usd": 1000000, "evm_only": True,
               "non_evm_chains": ["Solana", "Tron", "Sui"]}


def test_passes_chain_allows_evm_and_blocks_denylisted():
    assert filters.passes_chain({"chain": "Ethereum"}, EVM_FILTERS) is True
    assert filters.passes_chain({"chain": "Solana"}, EVM_FILTERS) is False
    assert filters.passes_chain({"chain": "tron"}, EVM_FILTERS) is False  # case-insensitive


def test_passes_chain_is_noop_when_evm_only_absent():
    assert filters.passes_chain({"chain": "Solana"}, {"min_tvl_usd": 1}) is True


def test_passes_filters_excludes_non_evm_when_evm_only():
    v = {"symbol": "USDC", "chain": "Solana", "tvlUsd": 5_000_000}
    assert filters.passes_filters(v, EVM_FILTERS, ALLOWED) is False
    v_evm = {**v, "chain": "Base"}
    assert filters.passes_filters(v_evm, EVM_FILTERS, ALLOWED) is True
