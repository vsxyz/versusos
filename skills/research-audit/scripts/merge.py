"""research-audit `merge` entrypoint (see SKILL.md).

Folds the verdict JSON returned by the research subagents into the slug-keyed
audit cache: invalid verdicts are skipped with a warning, valid ones are merged
with ``tvl_usd``/``audits_triage`` joined from the worklist and a ``researched_at``
stamp, and coverage is finalized. Run from this folder:
    python scripts/merge.py --verdicts data/verdicts.json [--worklist ...] [--out ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from core import verdicts
from core.common import DEFAULT_OUT, DEFAULT_WORKLIST, FMT, load_json, now, write_json


def _load_verdicts(path: str) -> list:
    """Load verdicts from a JSON-list file or a directory of per-slug *.json."""
    target = pathlib.Path(path)
    if target.is_dir():
        out = []
        for file in sorted(target.glob("*.json")):
            out.append(json.loads(file.read_text(encoding="utf-8")))
        return out
    loaded = load_json(path)
    return loaded if isinstance(loaded, list) else (loaded.get("verdicts") or [])


def run(args) -> int:
    worklist_doc = load_json(args.worklist)
    cache = load_json(args.cache)
    incoming = _load_verdicts(args.verdicts)
    valid, invalid = [], []
    for verdict in incoming:
        (invalid if verdicts.validate_verdict(verdict) else valid).append(verdict)
    for verdict in invalid:
        slug = verdict.get("slug", "?") if isinstance(verdict, dict) else "?"
        print(f"WARNING: skipping invalid verdict for {slug}", file=sys.stderr)
    by_project = verdicts.merge_verdicts(
        cache, worklist_doc.get("worklist", []), valid, now=now().strftime(FMT))
    coverage = dict(worklist_doc.get("coverage_preview") or {})
    coverage["researched"] = len(by_project)
    doc = {
        "source": "versusos_audit_research",
        "generated_at": now().strftime(FMT),
        "config": worklist_doc.get("config", {}),
        "coverage": coverage,
        "by_project": by_project,
        "skipped_below_floor": worklist_doc.get("skipped_below_floor", []),
    }
    write_json(doc, args.out)
    print(f"Merge: {len(valid)} verdicts ({len(invalid)} invalid skipped) -> "
          f"{args.out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="research-audit: fold verdict JSON into the audit cache.")
    parser.add_argument("--worklist", default=DEFAULT_WORKLIST)
    parser.add_argument("--verdicts", required=True)
    parser.add_argument("--cache", default=DEFAULT_OUT)
    parser.add_argument("--out", default=DEFAULT_OUT)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
