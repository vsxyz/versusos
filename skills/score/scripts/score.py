"""Score collected vaults: read caches -> join DEX pools -> score -> cache JSON.

Orchestrates the core/ modules: mapping (vault->pool join, grouped by target
token) and scoring (the points model). Reads the collect-vault and
collect-dex caches (both required) and, when present, the
contract_token_safety.json static mapping and the collect-depeg-history
ohlcv_history.json cache — never the network.
Run from this folder (no install needed):
    python scripts/score.py [--config ...] [--vaults ...] [--dex ...]
                            [--static ...] [--history ...] [--out ...]
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

from core import mapping, scoring

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "scoring.json")
DEFAULT_STATIC = str(SKILL_ROOT / "config" / "contract_token_safety.json")
DEFAULT_VAULTS = str(SKILL_ROOT.parent / "collect-vault" / "data" / "defillama_yields.json")
DEFAULT_DEX = str(SKILL_ROOT.parent / "collect-dex" / "data" / "dex_pools.json")
DEFAULT_HISTORY = str(SKILL_ROOT.parent / "collect-depeg-history" / "data" / "ohlcv_history.json")
DEFAULT_OUT = str(SKILL_ROOT / "data" / "vault_scores.json")

VAULT_FIELDS = ("pool", "project", "chain", "symbol", "tvlUsd", "apyBase", "apy")


def load_json(path: str) -> dict:
    """Load a JSON file into a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def load_json_optional(path: str) -> dict | None:
    """Load a JSON file, or None when it is absent (optional inputs)."""
    try:
        return load_json(path)
    except FileNotFoundError:
        return None


def _epoch(iso: str | None) -> float:
    """Parse a 'YYYY-MM-DDTHH:MM:SSZ' stamp to epoch seconds (0 when absent/bad)."""
    if not iso:
        return 0.0
    try:
        parsed = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return 0.0
    return parsed.replace(tzinfo=datetime.timezone.utc).timestamp()


def rank_key(record):
    """Safety rank key: order by the uniform ``normalized_score`` (0-100), with
    ``final_safety_score`` breaking ties so the deeper-analyzed vault wins at
    equal safety. Never order by ``final_safety_score`` alone — it mixes the
    0-100 (initial) and 0-200 (deep) scales, so a deep vault would float above a
    genuinely safer initial one purely by scale.
    """
    return (record["normalized_score"], record["final_safety_score"])


def build_payload(vault_payload, dex_payload, config, generated_at,
                  vaults_path, dex_path, *, static_payload=None,
                  history_payload=None, history_path=None) -> dict:
    """Join, score and rank every vault; assemble the cache payload."""
    pool_index = mapping.build_pool_index(dex_payload)
    mapping.merge_history(pool_index, history_payload)
    exploit_index = (vault_payload.get("exploits") or {}).get("by_project") or {}
    static_index = (static_payload or {}).get("by_pool") or {}
    fetched_at_epoch = _epoch(dex_payload.get("fetched_at"))
    scores = []
    for vault in vault_payload.get("vaults", []):
        pools_by_target = mapping.match_pools_by_target(vault, pool_index)
        record = {field: vault.get(field) for field in VAULT_FIELDS}
        record.update(scoring.score_vault(
            vault, pools_by_target, config,
            static_index=static_index,
            exploit_index=exploit_index, fetched_at_epoch=fetched_at_epoch))
        scores.append(record)
    scores.sort(key=rank_key, reverse=True)
    return {
        "source": "versusos_score",
        "generated_at": generated_at,
        "model": config.get("model", "points_v1"),
        "inputs": {
            "vaults": {"path": vaults_path,
                       "fetched_at": vault_payload.get("fetched_at")},
            "dex": {"path": dex_path,
                    "fetched_at": dex_payload.get("fetched_at")},
            "history": {"path": history_path,
                        "fetched_at": (history_payload or {}).get("fetched_at")},
        },
        "counts": {
            "vaults_scored": len(scores),
            "vaults_with_dex_data": sum(1 for r in scores if r["dex_pools_matched"]),
            "vaults_with_history": sum(1 for r in scores if r["basis"] == "deep"),
        },
        "scores": scores,
    }


def write_cache(payload: dict, out_path: str) -> None:
    """Write the payload to out_path as pretty JSON, creating parent dirs."""
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score collected stablecoin vaults.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--vaults", default=DEFAULT_VAULTS)
    parser.add_argument("--dex", default=DEFAULT_DEX)
    parser.add_argument("--static", default=DEFAULT_STATIC)
    parser.add_argument("--history", default=DEFAULT_HISTORY)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    config = load_json(args.config)
    try:
        vault_payload = load_json(args.vaults)
    except FileNotFoundError:
        print(f"Vault cache not found: {args.vaults}\n"
              "Run collect-vault first:  python skills/collect-vault/scripts/collect.py",
              file=sys.stderr)
        return 1
    try:
        dex_payload = load_json(args.dex)
    except FileNotFoundError:
        print(f"DEX cache not found: {args.dex}\n"
              "Run collect-dex first:  python skills/collect-dex/scripts/collect.py",
              file=sys.stderr)
        return 1
    static_payload = load_json_optional(args.static)
    history_payload = load_json_optional(args.history)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload = build_payload(vault_payload, dex_payload, config, generated_at,
                            args.vaults, args.dex, static_payload=static_payload,
                            history_payload=history_payload, history_path=args.history)
    write_cache(payload, args.out)
    counts = payload["counts"]
    print(f"Scored {counts['vaults_scored']} vaults "
          f"({counts['vaults_with_dex_data']} with dex, "
          f"{counts['vaults_with_history']} deep) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
