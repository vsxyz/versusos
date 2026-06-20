"""research-audit `plan` entrypoint (see SKILL.md).

Selects the top-N protocols by TVL from the collect-vault cache and emits a
worklist for the SKILL.md to research with subagents — dropping protocols whose
cached verdict is still fresh, and seeding each item with DeFiLlama audit_links.
Run from this folder:
    python scripts/plan.py [--vaults ...] [--top-n 50] [--out-worklist ...]
"""
from __future__ import annotations

import argparse
import sys

from core import llama, selection, verdicts
from core.common import DEFAULT_OUT, DEFAULT_WORKLIST, FMT, SKILL_ROOT, load_json, now, write_json

DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "collect.json")
DEFAULT_VAULTS = str(SKILL_ROOT.parent / "collect-vault" / "data"
                     / "defillama_yields.json")


def run(args) -> int:
    config = load_json(args.config)
    vault_cache = load_json(args.vaults)
    if not vault_cache.get("vaults"):
        print(f"ERROR: no vaults in {args.vaults}; run collect-vault first.",
              file=sys.stderr)
        return 1
    tvls = selection.project_tvls(vault_cache["vaults"])
    triage = (vault_cache.get("audit_triage") or {}).get("by_project") or {}
    top_n = args.top_n if args.top_n is not None else config.get("top_n", 50)
    ttl_days = config.get("ttl_days", 7)
    selected, skipped = selection.select_top_n(tvls, top_n)
    cache = load_json(args.cache)
    current = now()
    work = selection.build_worklist(
        selected, tvls, triage, cache.get("by_project") or {}, current, ttl_days)
    for item in work:
        item["audit_links"] = llama.fetch_audit_links(item["slug"])
    doc = {
        "generated_at": current.strftime(FMT),
        "config": {"top_n": top_n, "ttl_days": ttl_days},
        "selected": selected,
        "skipped_below_floor": skipped,
        "worklist": work,
        "coverage_preview": verdicts.compute_coverage(tvls, selected),
    }
    write_json(doc, args.out_worklist)
    print(f"Plan: {len(work)} to research / {len(selected)} selected / "
          f"{len(tvls)} total -> {args.out_worklist}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="research-audit: select top-N + emit research worklist.")
    parser.add_argument("--vaults", default=DEFAULT_VAULTS)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--cache", default=DEFAULT_OUT)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--out-worklist", default=DEFAULT_WORKLIST)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
