import importlib.util
import json
import pathlib

SCRIPTS = (pathlib.Path(__file__).resolve().parents[1]
           / "skills" / "collect-context" / "scripts")
_spec = importlib.util.spec_from_file_location("context_collect",
                                               SCRIPTS / "collect.py")
context_collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(context_collect)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def fake_call_tool_factory(overrides=None):
    payloads = {
        "search_cryptos": load_fixture("cmc_mcp_search_sample.json"),
        "get_crypto_latest_news": load_fixture("cmc_mcp_news_sample.json"),
        "get_global_metrics_latest": load_fixture("cmc_mcp_global_metrics_sample.json"),
        "trending_crypto_narratives": load_fixture("cmc_mcp_narratives_sample.json"),
    }
    payloads.update(overrides or {})
    calls = []

    def fake(name, arguments, *, api_key, **_):
        calls.append((name, arguments, api_key))
        value = payloads[name]
        if isinstance(value, Exception):
            raise value
        return value

    return fake, calls


def test_defaults_are_anchored_to_the_skill_folder():
    assert context_collect.DEFAULT_CONFIG.endswith("config/collect.json")
    assert context_collect.DEFAULT_OUT.endswith("data/context.json")
    assert context_collect.DEFAULT_MAPPING.endswith(
        "collect-vault/data/defillama_yields.json")
    assert pathlib.Path(context_collect.DEFAULT_CONFIG).is_file()


def test_mapping_symbols_splits_lp_pairs_and_dedupes():
    mapping = {"vaults": [
        {"symbol": "USDC-USDT"}, {"symbol": "usdc"}, {"symbol": "DAI"}]}
    assert context_collect.mapping_symbols(mapping) == ["USDC", "USDT", "DAI"]


def test_mapping_symbols_filters_to_whitelist():
    # a USDC/USDT-anchored pair's non-stable partner (WETH, ZEC) is dropped;
    # only whitelisted stablecoin tokens survive, in first-seen order.
    mapping = {"vaults": [
        {"symbol": "USDC-WETH"}, {"symbol": "ZEC-USDT"}, {"symbol": "DAI"}]}
    assert context_collect.mapping_symbols(
        mapping, whitelist=["USDC", "USDT", "DAI"]) == ["USDC", "USDT", "DAI"]


def test_mapping_symbols_appends_extra_on_request():
    # extras are added on top (upper-cased, de-duped) even when the whitelist
    # would exclude them or they are absent from the vault set.
    mapping = {"vaults": [{"symbol": "USDC"}, {"symbol": "ETH-USDC"}]}
    assert context_collect.mapping_symbols(
        mapping, whitelist=["USDC"], extra=["eth", "BTC", "usdc"]) == [
        "USDC", "ETH", "BTC"]


def test_mapping_symbols_no_whitelist_keeps_all():
    # no whitelist -> unfiltered (the --all-symbols path); back-compat.
    mapping = {"vaults": [{"symbol": "USDC-WETH"}]}
    assert context_collect.mapping_symbols(mapping) == ["USDC", "WETH"]


def test_main_writes_cache_and_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    fake, calls = fake_call_tool_factory()
    monkeypatch.setattr(context_collect.mcp, "call_tool", fake)
    out = tmp_path / "context.json"
    code = context_collect.main([
        "--mapping", str(FIXTURES / "context_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["source"] == "coinmarketcap-mcp"
    assert payload["fear_greed"] == {"value": 15,
                                     "classification": "Extreme fear"}
    # mapping fixture has USDC, DAI, CRVUSD; only USDC resolves in the
    # search fixture — the other two warn and carry empty news.
    assert [c["symbol"] for c in payload["stablecoins"]] == [
        "USDC", "DAI", "CRVUSD"]
    assert len(payload["stablecoins"][0]["news"]) == 2
    assert payload["stablecoins"][1]["news"] == []
    assert [n["rank"] for n in payload["narratives"]] == [1, 2]
    assert "test-key" not in out.read_text()  # key never lands in the cache
    err = capsys.readouterr().err
    assert "DAI" in err  # unresolved coin warned


def test_main_filters_nonstable_via_config_whitelist(monkeypatch, tmp_path):
    # the real config whitelist must drop a pair vault's non-stable partner.
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    fake, _ = fake_call_tool_factory()
    monkeypatch.setattr(context_collect.mcp, "call_tool", fake)
    mapping = tmp_path / "vaults.json"
    mapping.write_text(json.dumps({"vaults": [{"symbol": "USDC-WETH"}]}))
    out = tmp_path / "context.json"
    code = context_collect.main([
        "--mapping", str(mapping),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert [c["symbol"] for c in payload["stablecoins"]] == ["USDC"]


def test_main_extra_and_all_symbols_opt_in(monkeypatch, tmp_path):
    # --extra-symbols adds a coin on request; --all-symbols bypasses the filter.
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    fake, _ = fake_call_tool_factory()
    monkeypatch.setattr(context_collect.mcp, "call_tool", fake)
    mapping = tmp_path / "vaults.json"
    mapping.write_text(json.dumps({"vaults": [{"symbol": "USDC-WETH"}]}))
    cfg = str(SCRIPTS.parent / "config" / "collect.json")

    out1 = tmp_path / "extra.json"
    context_collect.main(["--mapping", str(mapping), "--config", cfg,
                          "--extra-symbols", "WETH", "--out", str(out1)])
    assert [c["symbol"] for c in json.loads(out1.read_text())["stablecoins"]] == [
        "USDC", "WETH"]

    out2 = tmp_path / "all.json"
    context_collect.main(["--mapping", str(mapping), "--config", cfg,
                          "--all-symbols", "--out", str(out2)])
    assert [c["symbol"] for c in json.loads(out2.read_text())["stablecoins"]] == [
        "USDC", "WETH"]


def test_main_partial_failure_still_writes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    fake, _ = fake_call_tool_factory(
        {"get_global_metrics_latest": RuntimeError("boom"),
         "trending_crypto_narratives": RuntimeError("boom")})
    monkeypatch.setattr(context_collect.mcp, "call_tool", fake)
    out = tmp_path / "context.json"
    code = context_collect.main([
        "--mapping", str(FIXTURES / "context_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["fear_greed"] is None
    assert payload["narratives"] == []
    assert "WARNING" in capsys.readouterr().err


def test_main_exits_one_when_nothing_collected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    fake, _ = fake_call_tool_factory(
        {"search_cryptos": RuntimeError("boom"),
         "get_crypto_latest_news": RuntimeError("boom"),
         "get_global_metrics_latest": RuntimeError("boom"),
         "trending_crypto_narratives": RuntimeError("boom")})
    monkeypatch.setattr(context_collect.mcp, "call_tool", fake)
    out = tmp_path / "context.json"
    code = context_collect.main([
        "--mapping", str(FIXTURES / "context_seed_vaults_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--out", str(out),
    ])
    assert code == 1
    assert not out.exists()
    assert "nothing collected" in capsys.readouterr().err


def test_resolve_api_key_env_wins_over_file(monkeypatch, tmp_path):
    key_file = tmp_path / ".env"
    key_file.write_text("CMC_PRO_API_KEY=from-file\n")
    monkeypatch.setattr(context_collect, "KEY_FILE", key_file)
    monkeypatch.setenv("CMC_PRO_API_KEY", "from-env")
    assert context_collect.resolve_api_key() == "from-env"


def test_resolve_api_key_reads_dotenv_file(monkeypatch, tmp_path):
    key_file = tmp_path / ".env"
    key_file.write_text(
        "# versusos credentials\n"
        "\n"
        "OTHER=nope\n"
        "CMC_PRO_API_KEY='from-file'\n")
    monkeypatch.setattr(context_collect, "KEY_FILE", key_file)
    monkeypatch.delenv("CMC_PRO_API_KEY", raising=False)
    assert context_collect.resolve_api_key() == "from-file"


def test_resolve_api_key_missing_everywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(context_collect, "KEY_FILE",
                        tmp_path / "missing.env")
    monkeypatch.delenv("CMC_PRO_API_KEY", raising=False)
    assert context_collect.resolve_api_key() is None
    empty = tmp_path / "no-key.env"
    empty.write_text("OTHER=nope\n")
    monkeypatch.setattr(context_collect, "KEY_FILE", empty)
    assert context_collect.resolve_api_key() is None


def test_main_exits_one_without_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CMC_PRO_API_KEY", raising=False)
    monkeypatch.setattr(context_collect, "KEY_FILE",
                        tmp_path / "missing.env")
    out = tmp_path / "context.json"
    code = context_collect.main(["--out", str(out)])
    assert code == 1
    assert not out.exists()
    assert "CMC_PRO_API_KEY" in capsys.readouterr().err
