from core import audit_triage

PROTOCOLS = [
    {"slug": "morpho-blue", "id": "1", "audits": "2"},   # API often sends a string
    {"slug": "comb-financial", "id": "2", "audits": 0},
    {"slug": "spark-savings", "id": "3", "audits": "1"},
    {"slug": "forked-thing", "id": "4", "audits": 3},
    {"slug": "nulled", "id": "5", "audits": None},
    {"slug": "weird", "id": "6", "audits": "n/a"},        # unparseable -> unknown
]


def test_audits_label_maps_codes():
    assert audit_triage._audits_label(0) == "none"
    assert audit_triage._audits_label(1) == "partial"
    assert audit_triage._audits_label(2) == "audited"
    assert audit_triage._audits_label(3) == "fork"
    assert audit_triage._audits_label(None) == "unknown"


def test_coerce_audits_normalizes_str_int_none():
    assert audit_triage._coerce_audits("2") == 2
    assert audit_triage._coerce_audits(0) == 0
    assert audit_triage._coerce_audits(None) is None
    assert audit_triage._coerce_audits("n/a") is None


def test_build_by_project_resolves_codes_and_labels():
    block = audit_triage.build_by_project(
        PROTOCOLS, ["morpho-blue", "comb-financial", "spark-savings"])
    assert block["source"] == "defillama_protocols"
    bp = block["by_project"]
    assert bp["morpho-blue"] == {"audits": 2, "audits_label": "audited"}
    assert bp["comb-financial"] == {"audits": 0, "audits_label": "none"}
    assert bp["spark-savings"] == {"audits": 1, "audits_label": "partial"}


def test_build_by_project_unparseable_and_null_become_unknown():
    block = audit_triage.build_by_project(PROTOCOLS, ["nulled", "weird"])
    bp = block["by_project"]
    assert bp["nulled"] == {"audits": None, "audits_label": "unknown"}
    assert bp["weird"] == {"audits": None, "audits_label": "unknown"}


def test_build_by_project_unresolved_listed_not_in_by_project():
    block = audit_triage.build_by_project(PROTOCOLS, ["morpho-blue", "ghost"])
    assert "ghost" not in block["by_project"]
    assert block["unresolved_projects"] == ["ghost"]


def test_build_by_project_sorts_and_dedupes_projects():
    block = audit_triage.build_by_project(
        PROTOCOLS, ["comb-financial", "morpho-blue", "morpho-blue"])
    assert list(block["by_project"].keys()) == ["comb-financial", "morpho-blue"]
