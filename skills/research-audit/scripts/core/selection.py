"""Pure, network-free selection logic for research-audit.

Decides *what* to research: aggregate per-project TVL from the collect-vault
cache, pick the top-N by TVL, classify each into a research track, and (against
the existing verdict cache + a TTL) compute the worklist of slugs that are
missing or stale. No network, no LLM — those live in the entrypoint / SKILL.md.
"""
from __future__ import annotations

import datetime

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def project_tvls(vaults: list[dict]) -> dict:
    """Sum ``tvlUsd`` per non-empty ``project`` slug across vault records."""
    totals: dict = {}
    for vault in vaults:
        slug = vault.get("project")
        if not slug:
            continue
        totals[slug] = totals.get(slug, 0) + (vault.get("tvlUsd") or 0)
    return totals


def select_top_n(tvls: dict, top_n: int) -> tuple[list, list]:
    """Return (selected, skipped) slugs: TVL descending, ties broken slug-ascending.

    ``selected`` is the first ``top_n``; ``skipped`` is the remainder (reported,
    never researched).
    """
    ordered = [slug for slug, _ in sorted(tvls.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ordered[:top_n], ordered[top_n:]


def classify_track(audits_code) -> str:
    """``'grade'`` for audited (code 2); ``'verify'`` for 0/1/3/None."""
    return "grade" if audits_code == 2 else "verify"


def is_stale(researched_at, now: datetime.datetime, ttl_days: int) -> bool:
    """True if ``researched_at`` is missing or older than ``ttl_days`` before now.

    ``researched_at`` is a ``YYYY-MM-DDTHH:MM:SSZ`` UTC string; ``now`` is an
    aware UTC datetime.
    """
    if not researched_at:
        return True
    stamped = datetime.datetime.strptime(researched_at, _FMT).replace(
        tzinfo=datetime.timezone.utc)
    return (now - stamped) > datetime.timedelta(days=ttl_days)


def build_worklist(selected: list, tvls: dict, triage_by_project: dict,
                   cache_by_project: dict, now: datetime.datetime,
                   ttl_days: int) -> list:
    """Worklist items for selected slugs that are missing or stale in the cache.

    A fresh cached entry is skipped (its verdict is reused). Each item carries the
    inputs a research subagent needs: ``{slug, tvl_usd, audits_triage, track}``.
    A slug absent from the triage map gets ``audits_triage: None`` (-> verify).
    """
    work = []
    for slug in selected:
        entry = cache_by_project.get(slug)
        if entry and not is_stale(entry.get("researched_at"), now, ttl_days):
            continue
        code = (triage_by_project.get(slug) or {}).get("audits")
        work.append({
            "slug": slug,
            "tvl_usd": tvls.get(slug, 0),
            "audits_triage": code,
            "track": classify_track(code),
        })
    return work


if __name__ == "__main__":
    raise SystemExit(
        "selection.py provides pure selection logic imported by plan.py — "
        "it is not a standalone entrypoint.\nRun:  python scripts/plan.py"
    )
