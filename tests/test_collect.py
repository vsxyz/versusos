import json
import pathlib

import collect

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


EXAMPLE_CONFIG = {
    "filters": {
        "tokens": {"groups": ["ALL_USD_STABLES"]},
        "min_tvl_usd": 1000000,
        "exclude_memecoins": True,
    },
    "sort": {"by": "apyBase", "desc": True},
}


def test_load_json_reads_json(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"filters": {"exposure": "single"}, "sort": {"by": "apyBase"}}')
    config = collect.load_json(str(path))
    assert config["filters"]["exposure"] == "single"
    assert config["sort"]["by"] == "apyBase"


def test_default_config_is_bundled_json():
    assert collect.DEFAULT_CONFIG.endswith("collect.json")
    assert pathlib.Path(collect.DEFAULT_CONFIG).is_file()


def test_build_payload_filters_sorts_and_counts():
    vaults = load_fixture("defillama_vaults_sample.json")["data"]
    usd = {"USDC", "USDT", "DAI"}
    payload = collect.build_payload(vaults, usd, EXAMPLE_CONFIG, "2026-06-09T00:00:00Z")
    assert payload["source"] == "defillama_yields"
    assert payload["fetched_at"] == "2026-06-09T00:00:00Z"
    assert payload["counts"] == {"fetched": 10, "after_filter": 3}
    assert [v["pool"] for v in payload["vaults"]] == ["p2", "p1", "p7"]
    assert payload["filters_applied"]["sort"] == {"by": "apyBase", "desc": True}


def test_resolve_usd_symbols_empty_when_group_absent():
    config = {"filters": {"tokens": {"groups": [], "symbols": ["EURC"]}}}
    assert collect._resolve_usd_symbols(config, []) == set()


def test_resolve_usd_symbols_uses_stablecoin_flag():
    vaults = [
        {"symbol": "USDC", "stablecoin": True},
        {"symbol": "WETH", "stablecoin": False},
    ]
    config = {"filters": {"tokens": {"groups": ["ALL_USD_STABLES"]}}}
    assert collect._resolve_usd_symbols(config, vaults) == {"USDC"}


PROTOCOLS_FX = [
    {"slug": "compound-v3", "id": "5", "parentProtocol": "parent#compound-finance",
     "audits": "2"},
    {"slug": "aave-v3", "id": "1599", "parentProtocol": "parent#aave", "audits": 0},
]
HACKS_FX = [
    {"date": 1700000000, "name": "Compound", "classification": "Protocol Logic",
     "amount": 147000000, "returnedFunds": 0, "defillamaId": 5,
     "parentProtocolId": "parent#compound-finance"},
]


def test_vault_projects_distinct_sorted_non_empty():
    vaults = [{"project": "aave-v3"}, {"project": "compound-v3"},
              {"project": "aave-v3"}, {"project": None}, {}]
    assert collect._vault_projects(vaults) == ["aave-v3", "compound-v3"]


def test_collect_protocol_blocks_builds_both_blocks():
    blocks = collect.collect_protocol_blocks(
        ["compound-v3", "aave-v3"],
        {"exploits": {"enabled": True, "version_propagation": "brand_wide"},
         "audit_triage": {"enabled": True}},
        fetched_at="2026-06-13T00:00:00Z",
        fetch_hacks=lambda: HACKS_FX,
        fetch_protocols=lambda: PROTOCOLS_FX,
    )
    ex = blocks["exploits"]
    assert ex["available"] is True and ex["fetched_at"] == "2026-06-13T00:00:00Z"
    assert ex["by_project"]["compound-v3"]["exploit_count"] == 1
    tr = blocks["audit_triage"]
    assert tr["available"] is True and tr["fetched_at"] == "2026-06-13T00:00:00Z"
    assert tr["by_project"]["compound-v3"] == {"audits": 2, "audits_label": "audited"}
    assert tr["by_project"]["aave-v3"] == {"audits": 0, "audits_label": "none"}


def test_collect_protocol_blocks_shares_one_protocols_fetch():
    calls = {"protocols": 0, "hacks": 0}

    def fetch_protocols():
        calls["protocols"] += 1
        return PROTOCOLS_FX

    def fetch_hacks():
        calls["hacks"] += 1
        return HACKS_FX

    collect.collect_protocol_blocks(
        ["compound-v3"],
        {"exploits": {"enabled": True}, "audit_triage": {"enabled": True}},
        fetched_at="2026-06-13T00:00:00Z",
        fetch_hacks=fetch_hacks, fetch_protocols=fetch_protocols,
    )
    assert calls == {"protocols": 1, "hacks": 1}  # /protocols fetched ONCE


def test_collect_protocol_blocks_triage_survives_hacks_failure():
    def boom():
        raise RuntimeError("hacks down")

    blocks = collect.collect_protocol_blocks(
        ["compound-v3"],
        {"exploits": {"enabled": True}, "audit_triage": {"enabled": True}},
        fetched_at="2026-06-13T00:00:00Z",
        fetch_hacks=boom, fetch_protocols=lambda: PROTOCOLS_FX,
    )
    assert blocks["exploits"] == {"available": False, "error": "hacks down"}
    assert blocks["audit_triage"]["available"] is True  # protocols ok -> triage ok


def test_collect_protocol_blocks_both_unavailable_on_protocols_failure():
    def boom():
        raise RuntimeError("protocols down")

    blocks = collect.collect_protocol_blocks(
        ["compound-v3"],
        {"exploits": {"enabled": True}, "audit_triage": {"enabled": True}},
        fetched_at="2026-06-13T00:00:00Z",
        fetch_hacks=lambda: HACKS_FX, fetch_protocols=boom,
    )
    assert blocks["exploits"] == {"available": False, "error": "protocols down"}
    assert blocks["audit_triage"] == {"available": False, "error": "protocols down"}


def test_collect_protocol_blocks_disabled_features_return_none():
    blocks = collect.collect_protocol_blocks(
        ["compound-v3"],
        {"exploits": {"enabled": False}, "audit_triage": {"enabled": False}},
        fetched_at="2026-06-13T00:00:00Z",
        fetch_hacks=lambda: HACKS_FX, fetch_protocols=lambda: PROTOCOLS_FX,
    )
    assert blocks == {"exploits": None, "audit_triage": None}


def test_augment_counts_with_available_block():
    payload = {
        "counts": {"fetched": 3, "after_filter": 2},
        "vaults": [{"project": "compound-v3"}, {"project": "aave-v3"}],
        "exploits": {
            "available": True,
            "by_project": {
                "compound-v3": {"exploit_count": 1, "resolved": True},
                "aave-v3": {"exploit_count": 0, "resolved": True},
            },
            "unresolved_projects": [],
        },
    }
    collect._augment_counts(payload)
    assert payload["counts"] == {
        "fetched": 3, "after_filter": 2, "projects": 2,
        "projects_resolved": 2, "projects_with_exploits": 1, "projects_unresolved": 0,
    }


def test_augment_counts_when_exploits_unavailable():
    payload = {
        "counts": {"fetched": 3, "after_filter": 2},
        "vaults": [{"project": "compound-v3"}],
        "exploits": {"available": False, "error": "boom"},
    }
    collect._augment_counts(payload)
    # projects still counted; resolved/with_exploits omitted when unavailable
    assert payload["counts"] == {"fetched": 3, "after_filter": 2, "projects": 1}


def test_augment_counts_adds_audit_triage_tallies():
    payload = {
        "counts": {"fetched": 3, "after_filter": 2},
        "vaults": [{"project": "compound-v3"}, {"project": "aave-v3"}],
        "audit_triage": {
            "available": True,
            "by_project": {
                "compound-v3": {"audits": 2, "audits_label": "audited"},
                "aave-v3": {"audits": 0, "audits_label": "none"},
            },
            "unresolved_projects": [],
        },
    }
    collect._augment_counts(payload)
    assert payload["counts"]["projects_audited"] == 1
    assert payload["counts"]["projects_unaudited"] == 1
