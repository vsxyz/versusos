import importlib.util
import json
import pathlib

SCRIPTS = (pathlib.Path(__file__).resolve().parents[1]
           / "skills" / "research-audit" / "scripts")


def _load(alias, filename):
    spec = importlib.util.spec_from_file_location(alias, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# plan.py / merge.py are unique top-level names but loaded by path to keep the
# module names explicit (and out of the generic ``plan`` / ``merge`` import space).
audit_plan = _load("audit_plan", "plan.py")
audit_merge = _load("audit_merge", "merge.py")

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_config_has_top_n_and_ttl():
    config = json.loads(
        (SCRIPTS.parent / "config" / "collect.json").read_text())
    assert config["top_n"] == 50
    assert config["ttl_days"] == 7


def test_defaults_anchored_to_skill_folder():
    assert audit_plan.DEFAULT_CONFIG.endswith("config/collect.json")
    assert audit_plan.DEFAULT_OUT.endswith("data/audit_research.json")
    assert pathlib.Path(audit_plan.DEFAULT_CONFIG).is_file()


def test_plan_writes_worklist_top_n_by_tvl(monkeypatch, tmp_path):
    # stub the audit_links seed so the test stays network-free
    monkeypatch.setattr(audit_plan.llama, "fetch_audit_links",
                        lambda slug, **_: [f"https://docs/{slug}"])
    out = tmp_path / "worklist.json"
    code = audit_plan.main([
        "--vaults", str(FIXTURES / "audit_vault_cache_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--cache", str(tmp_path / "missing-cache.json"),  # no prior cache
        "--top-n", "2",
        "--out-worklist", str(out),
    ])
    assert code == 0
    doc = json.loads(out.read_text())
    # top 2 by TVL: morpho-blue (3.5B) and comb-financial (1M); tiny-proto cut
    assert doc["selected"] == ["morpho-blue", "comb-financial"]
    assert doc["skipped_below_floor"] == ["tiny-proto"]
    slugs = [w["slug"] for w in doc["worklist"]]
    assert slugs == ["morpho-blue", "comb-financial"]
    morpho = next(w for w in doc["worklist"] if w["slug"] == "morpho-blue")
    assert morpho["tvl_usd"] == 3500000000
    assert morpho["audits_triage"] == 2 and morpho["track"] == "grade"
    assert morpho["audit_links"] == ["https://docs/morpho-blue"]
    assert doc["coverage_preview"]["projects_total"] == 3


def test_plan_skips_fresh_cached_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_plan.llama, "fetch_audit_links", lambda slug, **_: [])
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"by_project": {
        "morpho-blue": {"researched_at": "2099-01-01T00:00:00Z"}}}))  # always fresh
    out = tmp_path / "worklist.json"
    audit_plan.main([
        "--vaults", str(FIXTURES / "audit_vault_cache_sample.json"),
        "--config", str(SCRIPTS.parent / "config" / "collect.json"),
        "--cache", str(cache), "--top-n", "2", "--out-worklist", str(out),
    ])
    doc = json.loads(out.read_text())
    # morpho-blue is fresh -> not researched again; still counted as selected
    assert doc["selected"] == ["morpho-blue", "comb-financial"]
    assert [w["slug"] for w in doc["worklist"]] == ["comb-financial"]


def test_merge_writes_cache_skips_invalid(tmp_path):
    out = tmp_path / "audit_research.json"
    code = audit_merge.main([
        "--worklist", str(FIXTURES / "audit_worklist_sample.json"),
        "--verdicts", str(FIXTURES / "audit_verdicts_sample.json"),
        "--cache", str(tmp_path / "no-prior.json"),
        "--out", str(out),
    ])
    assert code == 0
    cache = json.loads(out.read_text())
    assert cache["source"] == "versusos_audit_research"
    bp = cache["by_project"]
    assert set(bp) == {"morpho-blue", "comb-financial"}   # 'broken' skipped
    assert bp["morpho-blue"]["score"] == 9
    assert bp["morpho-blue"]["tvl_usd"] == 3500000000     # joined from worklist
    assert bp["comb-financial"]["audited"] == "unknown"
    assert bp["comb-financial"]["score"] is None
    assert cache["coverage"]["researched"] == 2
    assert cache["coverage"]["tvl_covered_pct"] == 100.0
    assert cache["skipped_below_floor"] == ["tiny-proto"]


def test_merge_loads_verdicts_from_directory(tmp_path):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    (vdir / "morpho-blue.json").write_text(json.dumps({
        "slug": "morpho-blue", "classification": "audited", "audited": "yes",
        "score": 8, "confidence": "high", "sources": ["https://x"]}))
    out = tmp_path / "audit_research.json"
    code = audit_merge.main([
        "--worklist", str(FIXTURES / "audit_worklist_sample.json"),
        "--verdicts", str(vdir), "--cache", str(tmp_path / "no.json"),
        "--out", str(out)])
    assert code == 0
    cache = json.loads(out.read_text())
    assert cache["by_project"]["morpho-blue"]["score"] == 8
