"""Pure, network-free audit-triage builder for collect-vault.

Maps each vault ``project`` slug to its DeFiLlama ``audits`` code (the free
first-pass signal: 0=none, 1=partial, 2=audited, 3=fork-of-audited). The code is
already present in the ``/protocols`` payload collect.py fetches for the exploit
join, so this adds no network call. Quality verification/grading is the separate
``research-audit`` skill's job; this only surfaces the raw code + a label.
"""
from __future__ import annotations

_AUDITS_LABEL = {0: "none", 1: "partial", 2: "audited", 3: "fork"}


def _coerce_audits(value):
    """Normalize the API ``audits`` field (often a string) to int, else None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audits_label(code) -> str:
    """Map a coerced audits code to its label; anything off-table -> 'unknown'."""
    return _AUDITS_LABEL.get(code, "unknown")


def build_by_project(protocols: list[dict], projects) -> dict:
    """Build the ``audit_triage`` content block from ``/protocols`` + slugs.

    collect.py adds ``available`` / ``fetched_at``. ``projects`` is any iterable
    of slugs; output is sorted and deduped. Resolved slugs land in ``by_project``
    with ``{audits, audits_label}``; slugs absent from ``/protocols`` go to
    ``unresolved_projects`` only (no synthetic entry — the downstream skill treats
    a missing slug as unknown).
    """
    by_slug = {p["slug"]: p for p in protocols if p.get("slug")}
    by_project: dict = {}
    unresolved: list = []
    for slug in sorted(set(projects)):
        proto = by_slug.get(slug)
        if proto is None:
            unresolved.append(slug)
            continue
        code = _coerce_audits(proto.get("audits"))
        by_project[slug] = {"audits": code, "audits_label": _audits_label(code)}
    return {
        "source": "defillama_protocols",
        "by_project": by_project,
        "unresolved_projects": sorted(unresolved),
    }


if __name__ == "__main__":
    raise SystemExit(
        "audit_triage.py provides the pure audit-triage join imported by "
        "collect.py — it is not a standalone entrypoint and does nothing on its "
        "own.\nRun the collector instead:  python scripts/collect.py"
    )
