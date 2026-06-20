"""Collect depeg (daily) + dynamic (minute) OHLCV for the top-N scored vaults.

Opt-in deep step (run only on explicit user approval — see SKILL.md). Reads the
score skill's ranked vault_scores.json and the collect-dex cache, selects the
history_selected pools of the top-N vaults (core/targets.py), fetches GeckoTerminal
daily+minute OHLCV (core/geckoterminal.py, throttled, 429-aware), and writes its
own ohlcv_history.json. No API key needed. Run from this folder:
    python scripts/collect.py [--top-n 10] [--scores ...] [--dex ...] [--out ...]
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time

from core import geckoterminal, targets

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SCORES = str(SKILL_ROOT.parent / "score" / "data" / "vault_scores.json")
DEFAULT_DEX = str(SKILL_ROOT.parent / "collect-dex" / "data" / "dex_pools.json")
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "collect.json")
DEFAULT_OUT = str(SKILL_ROOT / "data" / "ohlcv_history.json")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def write_cache(payload: dict, out_path: str) -> None:
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def collect(target_list, options, *, existing=None, refresh=False,
            fetch_daily=geckoterminal.fetch_daily_ohlcv,
            fetch_minute=geckoterminal.fetch_minute_ohlcv, sleep=time.sleep) -> dict:
    """Fetch daily+minute OHLCV per target, throttled before *every* call; a
    failed fetch -> None.

    Keyed by "chain|pool_address|token_address". The throttle pauses before each
    GeckoTerminal request (not just between pools) so a pool's daily+minute calls
    never fire as a back-to-back burst — the dominant 429 trigger. Pieces already
    present (non-null) in ``existing`` are reused instead of re-fetched unless
    ``refresh``, so re-runs only fill gaps, make far fewer calls, and never regress
    a good cache. A target without a gecko_network, or whose address is not
    GeckoTerminal-fetchable, warns and is recorded with null OHLCV.
    """
    existing = existing or {}
    minutes = int(options["minute_window_hours"] * 60)
    throttle = options["throttle_seconds"]
    by_pool: dict[str, dict] = dict(existing)  # keep pools outside this run's targets
    daily_ok = minute_ok = skipped_non_address = 0
    state = {"called": False}  # throttle before every call except the very first

    def throttled(do_fetch):
        if state["called"]:
            sleep(throttle)
        state["called"] = True
        return do_fetch()

    for target in target_list:
        chain, addr = target["chain"], target["pool_address"]
        tok = target["token_address"]
        key = f"{chain}|{addr}|{tok}"
        prev = existing.get(key) or {}
        entry = {"chain": chain, "pool_address": addr, "token_address": tok,
                 "ohlcv_daily": prev.get("ohlcv_daily"),
                 "ohlcv_minute": prev.get("ohlcv_minute")}
        network = target.get("gecko_network")
        if not network:
            print(f"WARNING: no GeckoTerminal network for {target.get('symbol')} "
                  f"on {chain}; skipped.", file=sys.stderr)
            by_pool[key] = entry
            continue
        if not geckoterminal.is_contract_address(addr):
            print(f"WARNING: pool {addr} ({target.get('symbol')} "
                  f"on {chain}) is not a GeckoTerminal-fetchable address "
                  f"(Uniswap v4 / Curve composite); skipped.", file=sys.stderr)
            skipped_non_address += 1
            by_pool[key] = entry
            continue
        if refresh or entry["ohlcv_daily"] is None:
            try:
                entry["ohlcv_daily"] = throttled(lambda: fetch_daily(
                    network, addr, days=options["history_days"], token_address=tok))
            except RuntimeError as error:
                print(f"WARNING: daily history failed for {addr}: {error}",
                      file=sys.stderr)
        if refresh or entry["ohlcv_minute"] is None:
            try:
                entry["ohlcv_minute"] = throttled(lambda: fetch_minute(
                    network, addr, minutes=minutes, token_address=tok))
            except RuntimeError as error:
                print(f"WARNING: minute history failed for {addr}: {error}",
                      file=sys.stderr)
        if entry["ohlcv_daily"] is not None:
            daily_ok += 1
        if entry["ohlcv_minute"] is not None:
            minute_ok += 1
        by_pool[key] = entry
    counts = {"targets": len(target_list), "daily_ok": daily_ok,
              "minute_ok": minute_ok, "skipped_non_address": skipped_non_address}
    return {"by_pool": by_pool, "counts": counts}


def main(argv=None, *, fetch_daily=geckoterminal.fetch_daily_ohlcv,
         fetch_minute=geckoterminal.fetch_minute_ohlcv, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(
        description="Deep-collect depeg/dynamic OHLCV for the top-N scored vaults.")
    parser.add_argument("--scores", default=DEFAULT_SCORES)
    parser.add_argument("--dex", default=DEFAULT_DEX)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the existing cache and re-fetch every pool "
                             "(default: reuse already-collected pools, fetch only gaps)")
    args = parser.parse_args(argv)

    options = load_json(args.config)
    top_n = args.top_n if args.top_n is not None else options["top_n"]
    try:
        scores_payload = load_json(args.scores)
        dex_payload = load_json(args.dex)
    except FileNotFoundError as error:
        print(f"ERROR: required cache not found: {error.filename}\n"
              "Run score (and collect-dex) first.", file=sys.stderr)
        return 1

    target_list = targets.select_targets(
        scores_payload.get("scores"), dex_payload, top_n)
    if not target_list:
        print("ERROR: no targets — no history_selected pools for the top-N vaults "
              "(cache not written).", file=sys.stderr)
        return 1

    existing = {}
    if not args.refresh:  # resume: reuse pools already collected, only fill gaps
        try:
            existing = (load_json(args.out) or {}).get("by_pool") or {}
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}

    payload = collect(target_list, options, existing=existing, refresh=args.refresh,
                      fetch_daily=fetch_daily, fetch_minute=fetch_minute, sleep=sleep)
    counts = payload["counts"]
    if counts["daily_ok"] == 0 and counts["minute_ok"] == 0:
        print("ERROR: no OHLCV collected for any target; cache not written "
              "(existing cache preserved).", file=sys.stderr)
        return 1
    payload["source"] = "geckoterminal"
    payload["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload["history_window_days"] = options["history_days"]
    payload["minute_window_hours"] = options["minute_window_hours"]
    write_cache(payload, args.out)
    print(f"History for {counts['targets']} pools: daily {counts['daily_ok']}, "
          f"minute {counts['minute_ok']}, skipped {counts['skipped_non_address']} "
          f"(non-address) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
