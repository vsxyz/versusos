"""Resolve a token contract address to its scored stablecoin vaults (inspect).

Reads the collect-vault cache (the CA index via ``underlyingTokens``) and the
score cache, matches the address(es) with core.matching, and prints the matched
vaults as JSON to stdout for the inspect SKILL to present. Network-free: naming
an out-of-coverage token lives in naming.py and is invoked separately by the
SKILL. Run from this folder (no install needed):
    python scripts/resolve.py --addresses 0x... [--chain ethereum]
                              [--vaults ...] [--scores ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from core import matching

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_VAULTS = str(SKILL_ROOT.parent / "collect-vault" / "data" / "defillama_yields.json")
DEFAULT_SCORES = str(SKILL_ROOT.parent / "score" / "data" / "vault_scores.json")


def load_json(path: str) -> dict:
    """Load a JSON file into a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a token CA to its scored stablecoin vaults.")
    parser.add_argument("--addresses", nargs="+", required=True)
    parser.add_argument("--chain", default=None)
    parser.add_argument("--vaults", default=DEFAULT_VAULTS)
    parser.add_argument("--scores", default=DEFAULT_SCORES)
    args = parser.parse_args(argv)

    try:
        vault_payload = load_json(args.vaults)
    except FileNotFoundError:
        print(f"Vault cache not found: {args.vaults}\n"
              "Run collect (or recommend) first to build the scored universe.",
              file=sys.stderr)
        return 1
    try:
        score_payload = load_json(args.scores)
    except FileNotFoundError:
        print(f"Score cache not found: {args.scores}\n"
              "Run score (or recommend) first to build the scored universe.",
              file=sys.stderr)
        return 1

    valid = [a for a in args.addresses if matching.is_evm_address(a)]
    rejected = [a for a in args.addresses if not matching.is_evm_address(a)]
    matches = matching.match_token(valid, vault_payload, score_payload, chain=args.chain)
    json.dump({
        "query": {"addresses": [a.lower() for a in args.addresses],
                  "chain": args.chain or None},
        "count": len(matches),
        "matches": matches,
        "rejected_non_evm": rejected,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
