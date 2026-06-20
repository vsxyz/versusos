"""Deductive Pick-bucket recommender: read the score cache -> gate/bucket -> JSON.

Pure orchestration over core.ranking; reads ``vault_scores.json`` and the
recommend config, never the network. The SKILL presents the result (top
``reps_per_bucket`` per bucket initially; up to ``expand_count`` on a strategy
pick). Run from this folder (no install needed):
    python scripts/recommend.py --asset USDT [--scores ...] [--config ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from core import ranking

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "recommend.json")
DEFAULT_SCORES = str(SKILL_ROOT.parent / "score" / "data" / "vault_scores.json")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deductive Pick-bucket recommender.")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--scores", default=DEFAULT_SCORES)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    try:
        config = load_json(args.config)
    except FileNotFoundError:
        print(f"Config not found: {args.config}\n"
              "Pass --config or restore the bundled recommend.json.",
              file=sys.stderr)
        return 1
    try:
        score_payload = load_json(args.scores)
    except FileNotFoundError:
        print(f"Score cache not found: {args.scores}\n"
              "Run score (or collect then score) first to build the scored universe.",
              file=sys.stderr)
        return 1

    result = ranking.bucketize(score_payload.get("scores") or [], config, args.asset)
    result["generated_at"] = score_payload.get("generated_at")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
