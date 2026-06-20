"""Shared file/timestamp helpers for the research-audit entrypoints.

``plan.py`` and ``merge.py`` both read and write the skill's JSON caches and
stamp UTC timestamps; those helpers and the shared path defaults live here so
there is a single source of truth. Pure stdlib, network-free.
"""
from __future__ import annotations

import datetime
import json
import pathlib

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUT = str(SKILL_ROOT / "data" / "audit_research.json")
DEFAULT_WORKLIST = str(SKILL_ROOT / "data" / "audit_worklist.json")
FMT = "%Y-%m-%dT%H:%M:%SZ"


def load_json(path: str) -> dict:
    """Load a JSON file into a dict; missing file -> empty dict."""
    file = pathlib.Path(path)
    if not file.exists():
        return {}
    with open(file, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def write_json(payload: dict, out_path: str) -> None:
    """Write payload as pretty JSON, creating parent dirs."""
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def now() -> datetime.datetime:
    """Current time as an aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


if __name__ == "__main__":
    raise SystemExit(
        "common.py provides shared file/timestamp helpers imported by plan.py "
        "and merge.py — it is not a standalone entrypoint.\n"
        "Run:  python scripts/plan.py  (or scripts/merge.py)"
    )
