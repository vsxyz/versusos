"""Collect DeFiLlama yield data: fetch -> filter -> sort -> cache to JSON.

Orchestrates the core/ library modules: defillama (network) and filters (pure).
Run from this folder (no install needed):
    python scripts/collect.py [--config config/collect.json] [--out data/...]
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib

from core import audit_triage, defillama, exploits, filters

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "collect.json")
DEFAULT_OUT = str(SKILL_ROOT / "data" / "defillama_yields.json")


def load_json(path: str) -> dict:
    """Load a JSON file into a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def build_payload(vaults: list[dict], usd_symbols: set[str],
                  config: dict, fetched_at: str) -> dict:
    """Filter + sort vaults and assemble the cache payload (pure)."""
    filter_config = config.get("filters", {})
    sort_config = config.get("sort", {})
    allowed = filters.build_allowed_symbols(filter_config.get("tokens", {}), usd_symbols)
    filtered = filters.filter_vaults(vaults, filter_config, allowed)
    if sort_config.get("by"):
        filtered = filters.sort_vaults(filtered, sort_config["by"], bool(sort_config.get("desc")))
    return {
        "source": "defillama_yields",
        "fetched_at": fetched_at,
        "filters_applied": {"filters": filter_config, "sort": sort_config},
        "counts": {"fetched": len(vaults), "after_filter": len(filtered)},
        "vaults": filtered,
    }


def _vault_projects(vaults: list[dict]) -> list[str]:
    """Distinct, sorted, non-empty ``project`` slugs across the given vaults."""
    return sorted({v.get("project") for v in vaults if v.get("project")})


def collect_protocol_blocks(projects: list[str], config: dict, *, fetched_at: str,
                            fetch_hacks=None, fetch_protocols=None) -> dict:
    """Fetch the DeFiLlama ``/hacks`` + ``/protocols`` sources once and build both
    protocol-keyed enrichment blocks: ``exploits`` (hacks join) and
    ``audit_triage`` (audits codes).

    Returns ``{"exploits": <block|None>, "audit_triage": <block|None>}``. A block
    is ``None`` when its feature is disabled (caller omits the key). ``/protocols``
    is fetched once and shared. Best-effort: a fetch failure marks the affected
    block ``{"available": False, "error": ...}`` rather than raising, so vault
    collection always succeeds; the pure joins run outside the fetch try so logic
    bugs surface. ``fetch_*`` default to the defillama clients; tests inject fakes.
    """
    fetch_hacks = fetch_hacks or defillama.fetch_hacks
    fetch_protocols = fetch_protocols or defillama.fetch_protocols
    ex_config = config.get("exploits", {})
    triage_config = config.get("audit_triage", {})
    exploits_enabled = ex_config.get("enabled", True)
    triage_enabled = triage_config.get("enabled", True)

    protocols = None
    protocols_err = None
    if exploits_enabled or triage_enabled:
        try:
            protocols = fetch_protocols()
        except Exception as error:  # network / HTTP / JSON parse
            protocols_err = str(error)

    exploits_block = None
    if exploits_enabled:
        hacks = None
        hacks_err = None
        try:
            hacks = fetch_hacks()
        except Exception as error:
            hacks_err = str(error)
        error = protocols_err or hacks_err
        if error:
            exploits_block = {"available": False, "error": error}
        else:
            exploits_block = exploits.build_by_project(hacks, protocols, projects, ex_config)
            exploits_block["available"] = True
            exploits_block["fetched_at"] = fetched_at

    triage_block = None
    if triage_enabled:
        if protocols_err:
            triage_block = {"available": False, "error": protocols_err}
        else:
            triage_block = audit_triage.build_by_project(protocols, projects)
            triage_block["available"] = True
            triage_block["fetched_at"] = fetched_at

    return {"exploits": exploits_block, "audit_triage": triage_block}


def _augment_counts(payload: dict) -> None:
    """Add project/exploit tallies to ``payload['counts']`` in place."""
    counts = payload["counts"]
    counts["projects"] = len(_vault_projects(payload["vaults"]))
    block = payload.get("exploits")
    if block and block.get("available"):
        by_project = block["by_project"]
        counts["projects_resolved"] = sum(1 for p in by_project.values() if p.get("resolved"))
        counts["projects_with_exploits"] = sum(
            1 for p in by_project.values() if p.get("exploit_count", 0) > 0)
        counts["projects_unresolved"] = len(block.get("unresolved_projects", []))
    triage = payload.get("audit_triage")
    if triage and triage.get("available"):
        by_triage = triage["by_project"]
        counts["projects_audited"] = sum(
            1 for p in by_triage.values() if p.get("audits") == 2)
        counts["projects_unaudited"] = sum(
            1 for p in by_triage.values() if p.get("audits") == 0)


def write_cache(payload: dict, out_path: str) -> None:
    """Write the payload to out_path as pretty JSON, creating parent dirs."""
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _resolve_usd_symbols(config: dict, vaults: list[dict]) -> set[str]:
    """Resolve the USD-stable symbol set needed to expand ALL_USD_STABLES.

    Returns empty when the group is not requested. Authoritative classification is
    the designated DEX's job (peg behavior on it); until that client lands, this is
    resolved **interim** from the DeFiLlama Yields ``stablecoin`` flag on the
    already-fetched vaults — broader than a true USD-peg set, but needs no extra
    network call.
    """
    groups = (config.get("filters", {}).get("tokens", {}).get("groups")) or []
    if "ALL_USD_STABLES" not in groups:
        return set()
    return {
        symbol
        for vault in vaults
        if vault.get("stablecoin") is True
        for symbol in filters.vault_token_symbols(vault)
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect DeFiLlama yield data.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    config = load_json(args.config)
    vaults = defillama.fetch_vaults()
    usd_symbols = _resolve_usd_symbols(config, vaults)
    fetched_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = build_payload(vaults, usd_symbols, config, fetched_at)
    blocks = collect_protocol_blocks(_vault_projects(payload["vaults"]), config,
                                     fetched_at=fetched_at)
    if blocks["exploits"] is not None:
        payload["exploits"] = blocks["exploits"]
    if blocks["audit_triage"] is not None:
        payload["audit_triage"] = blocks["audit_triage"]
    _augment_counts(payload)
    write_cache(payload, args.out)
    counts = payload["counts"]
    print(f"Collected {counts['after_filter']} / {counts['fetched']} vaults -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
