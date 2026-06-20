"""Pure, network-free verdict handling for research-audit.

Validates a research subagent's structured output, folds valid verdicts into the
slug-keyed cache (preserving untouched entries, stamping ``researched_at``), and
computes TVL coverage. Hand-rolled validation keeps the skill stdlib-only.
"""
from __future__ import annotations

_CLASSIFICATIONS = {"audited", "false_negative", "rwa", "unaudited", "partial",
                    "fork", "unknown"}
_AUDITED = {"yes", "no", "unknown"}
_CONFIDENCE = {"high", "medium", "low"}


def validate_verdict(verdict) -> list:
    """Return a list of problems with one verdict (empty list = valid).

    Enforces required fields and domains, the 0–10 integer score range, and the
    rule that an ``unknown`` verdict must carry a ``null`` score (never fabricate
    a number for an undeterminable protocol).
    """
    if not isinstance(verdict, dict):
        return ["not an object"]
    problems = []
    if not verdict.get("slug"):
        problems.append("missing slug")
    if verdict.get("classification") not in _CLASSIFICATIONS:
        problems.append("bad classification")
    if verdict.get("audited") not in _AUDITED:
        problems.append("bad audited")
    if verdict.get("confidence") not in _CONFIDENCE:
        problems.append("bad confidence")
    score = verdict.get("score")
    if verdict.get("audited") == "unknown":
        if score is not None:
            problems.append("unknown must have null score")
    elif not (isinstance(score, int) and not isinstance(score, bool)
              and 0 <= score <= 10):
        problems.append("score must be int 0-10")
    if not isinstance(verdict.get("sources"), list):
        problems.append("sources must be a list")
    return problems


def merge_verdicts(cache: dict, worklist: list, incoming: list, *, now: str) -> dict:
    """Fold validated ``incoming`` verdicts into ``cache['by_project']`` by slug.

    ``worklist`` supplies ``tvl_usd`` + ``audits_triage`` per slug; ``now`` stamps
    ``researched_at``. Invalid verdicts are skipped (the caller logs them).
    Existing entries not in ``incoming`` are preserved. Returns the updated
    ``by_project`` dict (a copy).
    """
    by_project = dict(cache.get("by_project") or {})
    work_by_slug = {w["slug"]: w for w in worklist}
    for verdict in incoming:
        if validate_verdict(verdict):
            continue
        slug = verdict["slug"]
        work = work_by_slug.get(slug, {})
        by_project[slug] = {
            "tvl_usd": work.get("tvl_usd"),
            "audits_triage": work.get("audits_triage"),
            "classification": verdict["classification"],
            "audited": verdict["audited"],
            "score": verdict.get("score"),
            "confidence": verdict["confidence"],
            "auditors": verdict.get("auditors") or [],
            "reports": verdict.get("reports") or [],
            "bug_bounty": verdict.get("bug_bounty"),
            "rwa_evidence": verdict.get("rwa_evidence"),
            "exploits_seen": verdict.get("exploits_seen", 0),
            "sources": verdict.get("sources") or [],
            "notes": verdict.get("notes", ""),
            "researched_at": now,
        }
    return by_project


def compute_coverage(tvls: dict, selected: list) -> dict:
    """TVL coverage of the selected slugs over the whole universe."""
    total = sum(tvls.values()) or 1
    covered = sum(tvls.get(slug, 0) for slug in selected)
    return {
        "projects_total": len(tvls),
        "selected": len(selected),
        "tvl_covered_pct": round(covered / total * 100, 1),
    }


if __name__ == "__main__":
    raise SystemExit(
        "verdicts.py provides pure verdict handling imported by plan.py / merge.py — "
        "it is not a standalone entrypoint.\nRun:  python scripts/merge.py"
    )
