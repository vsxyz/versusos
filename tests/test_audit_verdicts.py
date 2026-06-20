from core import verdicts

GOOD = {
    "slug": "morpho-blue", "classification": "audited", "audited": "yes",
    "score": 9, "confidence": "high", "auditors": ["OpenZeppelin"],
    "reports": [], "bug_bounty": None, "rwa_evidence": None,
    "exploits_seen": 0, "sources": ["https://example.com/report"], "notes": "ok",
}


def test_validate_accepts_good_verdict():
    assert verdicts.validate_verdict(GOOD) == []


def test_validate_unknown_must_have_null_score():
    v = {**GOOD, "audited": "unknown", "score": None}
    assert verdicts.validate_verdict(v) == []
    bad = {**GOOD, "audited": "unknown", "score": 5}
    assert "unknown must have null score" in verdicts.validate_verdict(bad)


def test_validate_flags_bad_domains_and_score_range():
    assert "bad classification" in verdicts.validate_verdict({**GOOD, "classification": "x"})
    assert "bad confidence" in verdicts.validate_verdict({**GOOD, "confidence": "x"})
    assert "score must be int 0-10" in verdicts.validate_verdict({**GOOD, "score": 11})
    assert "score must be int 0-10" in verdicts.validate_verdict({**GOOD, "score": True})
    assert "missing slug" in verdicts.validate_verdict({**GOOD, "slug": ""})


def test_merge_folds_valid_skips_invalid_and_stamps():
    worklist = [{"slug": "morpho-blue", "tvl_usd": 100, "audits_triage": 2},
                {"slug": "bad", "tvl_usd": 5, "audits_triage": 0}]
    incoming = [GOOD, {**GOOD, "slug": "bad", "confidence": "nope"}]
    by_project = verdicts.merge_verdicts({}, worklist, incoming, now="2026-06-13T00:00:00Z")
    assert "bad" not in by_project                       # invalid skipped
    entry = by_project["morpho-blue"]
    assert entry["tvl_usd"] == 100 and entry["audits_triage"] == 2
    assert entry["score"] == 9 and entry["researched_at"] == "2026-06-13T00:00:00Z"
    assert entry["auditors"] == ["OpenZeppelin"]


def test_merge_preserves_untouched_existing_entries():
    cache = {"by_project": {"old": {"score": 7, "researched_at": "2026-06-10T00:00:00Z"}}}
    by_project = verdicts.merge_verdicts(
        cache, [{"slug": "morpho-blue", "tvl_usd": 1, "audits_triage": 2}],
        [GOOD], now="2026-06-13T00:00:00Z")
    assert by_project["old"]["score"] == 7               # retained
    assert "morpho-blue" in by_project


def test_compute_coverage_pct():
    tvls = {"a": 90, "b": 9, "c": 1}
    cov = verdicts.compute_coverage(tvls, ["a", "b"])
    assert cov == {"projects_total": 3, "selected": 2, "tvl_covered_pct": 99.0}
