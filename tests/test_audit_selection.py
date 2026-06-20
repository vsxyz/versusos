import datetime

from core import selection

UTC = datetime.timezone.utc


def test_project_tvls_sums_per_slug():
    vaults = [
        {"project": "a", "tvlUsd": 100}, {"project": "a", "tvlUsd": 50},
        {"project": "b", "tvlUsd": 200}, {"project": None, "tvlUsd": 9},
        {"project": "c"},  # missing tvlUsd -> 0
    ]
    assert selection.project_tvls(vaults) == {"a": 150, "b": 200, "c": 0}


def test_select_top_n_orders_by_tvl_desc_ties_by_slug():
    tvls = {"a": 150, "b": 200, "c": 200, "d": 10}
    selected, skipped = selection.select_top_n(tvls, 2)
    assert selected == ["b", "c"]   # 200 ties -> slug asc; both make the cut
    assert skipped == ["a", "d"]


def test_classify_track():
    assert selection.classify_track(2) == "grade"
    for code in (0, 1, 3, None):
        assert selection.classify_track(code) == "verify"


def test_is_stale_missing_or_old():
    now = datetime.datetime(2026, 6, 13, tzinfo=UTC)
    assert selection.is_stale(None, now, 7) is True
    assert selection.is_stale("2026-06-01T00:00:00Z", now, 7) is True   # 12d old
    assert selection.is_stale("2026-06-10T00:00:00Z", now, 7) is False  # 3d old


def test_build_worklist_includes_missing_and_stale_skips_fresh():
    now = datetime.datetime(2026, 6, 13, tzinfo=UTC)
    tvls = {"fresh": 100, "stale": 90, "missing": 80}
    triage = {"fresh": {"audits": 2}, "stale": {"audits": 0}}  # 'missing' absent -> None
    cache = {
        "fresh": {"researched_at": "2026-06-12T00:00:00Z"},   # 1d -> fresh, skip
        "stale": {"researched_at": "2026-05-01T00:00:00Z"},   # old -> include
    }
    work = selection.build_worklist(
        ["fresh", "stale", "missing"], tvls, triage, cache, now, 7)
    assert [w["slug"] for w in work] == ["stale", "missing"]
    assert work[0] == {"slug": "stale", "tvl_usd": 90, "audits_triage": 0, "track": "verify"}
    assert work[1] == {"slug": "missing", "tvl_usd": 80, "audits_triage": None, "track": "verify"}
