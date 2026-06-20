"""Collect discovered-DEX pool data: discover -> snapshot -> JSON cache.

Targets are seeded from the collect-vault cache (vaults[].underlyingTokens).
Orchestrates the core/ modules: discovery (pure seed/filter/select), dexscreener
(token-pairs discovery + pooled amounts), cmc (CMC v4 DEX quotes — primary
snapshot, batched per chain; requires the CMC_PRO_API_KEY env var) and dexpools
(pure shaping). OHLCV history is not collected here — see the collect-depeg-history
skill for the deep OHLCV pass. The CMC key comes from ~/.versusos/.env
(CMC_PRO_API_KEY=<key>) or the CMC_PRO_API_KEY env var.
Run from this folder (no install needed):
    python scripts/collect.py [--vaults ...] [--config config/collect.json]
                              [--out data/dex_pools.json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time

from core import cmc, dexpools, dexscreener, discovery

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_VAULTS = str(SKILL_ROOT.parent / "collect-vault" / "data"
                     / "defillama_yields.json")
DEFAULT_CONFIG = str(SKILL_ROOT / "config" / "collect.json")
DEFAULT_OUT = str(SKILL_ROOT / "data" / "dex_pools.json")

ENV_KEY = "CMC_PRO_API_KEY"
KEY_FILE = pathlib.Path.home() / ".versusos" / ".env"


def resolve_api_key() -> str | None:
    """CMC_PRO_API_KEY from the environment, else from ~/.versusos/.env.

    The key file is dotenv-style: KEY=VALUE lines, # comments and blank
    lines ignored, optional surrounding quotes stripped. Module-global
    KEY_FILE is read at call time so tests can monkeypatch it.
    """
    value = os.environ.get(ENV_KEY)
    if value:
        return value
    try:
        lines = KEY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip() == ENV_KEY:
            return value.strip().strip("'\"") or None
    return None


def load_json(path: str) -> dict:
    """Load a JSON file into a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def write_cache(payload: dict, out_path: str) -> None:
    """Write the payload to out_path as pretty JSON, creating parent dirs."""
    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def collect_discovery(seeds: list[dict], whitelist_by_chain: dict, *,
                      fetch_token_pools=dexscreener.fetch_token_pools,
                      sleep=time.sleep, throttle_seconds: float = 0.0):
    """Discover USDC/USDT-paired pools per seed -> (jobs, ds_pairs_by_chain).

    One Dexscreener token-pairs call per seed (throttled when configured). A
    seed whose fetch fails warns and contributes no pools (the run continues).
    Pools are filtered to whitelisted counterparties by
    discovery.pools_from_token_pairs.
    """
    jobs: list[dict] = []
    ds_pairs_by_chain: dict[str, dict] = {}
    for index, seed in enumerate(seeds):
        if index and throttle_seconds:
            sleep(throttle_seconds)
        whitelist = whitelist_by_chain.get(seed["chain"], set())
        try:
            pairs = fetch_token_pools(seed["chain"], seed["token_address"])
        except RuntimeError as error:
            print(f"WARNING: discovery failed for {seed['token_address']} on "
                  f"{seed['chain']}: {error}", file=sys.stderr)
            continue
        seed_jobs, seed_ds = discovery.pools_from_token_pairs(
            pairs, seed, whitelist)
        jobs.extend(seed_jobs)
        ds_pairs_by_chain.setdefault(seed["chain"], {}).update(seed_ds)
    return jobs, ds_pairs_by_chain


def _chunked(items: list, size: int):
    """Yield successive ``size``-length slices of ``items`` (size <= 0 -> one slice)."""
    if size <= 0:
        yield list(items)
        return
    for start in range(0, len(items), size):
        yield items[start:start + size]


def collect_snapshots(jobs: list[dict], api_key: str, *,
                      fetch_pairs=cmc.fetch_pairs, batch_size: int = 100,
                      cmc_networks: list | None = None) -> dict:
    """CMC quotes per chain, address-validated and chunked, keyed per chain.

    Each chain's pool addresses are filtered to plain contract addresses
    (``cmc.is_contract_address`` — CMC 400s on pool-id hashes and Curve composite
    addresses) and split into ``batch_size`` chunks so a long address list does
    not overflow the request URI (HTTP 414). Each chunk is one batched call; a
    failed chunk warns and is skipped — its pools, and any address filtered out
    here, fall back to the Dexscreener snapshot in build_snapshot — so one bad
    chunk never costs a whole chain.

    ``cmc_networks`` is the allowlist of networks CMC's DEX API serves; a chain
    whose network is absent (e.g. bsc/avalanche, which 400 "network is not
    supported") is skipped entirely and left to the Dexscreener fallback. When
    None, every network is attempted (back-compat).
    """
    supported = set(cmc_networks) if cmc_networks is not None else None
    pairs_by_chain: dict[str, dict] = {}
    chains = list(dict.fromkeys(job["chain"] for job in jobs))
    for chain in chains:
        chain_jobs = [job for job in jobs if job["chain"] == chain]
        network = chain_jobs[0]["network"]
        if supported is not None and network not in supported:
            print(f"INFO: chain {chain} (network {network}) is not served by the "
                  f"CMC DEX API — using the Dexscreener snapshot fallback.",
                  file=sys.stderr)
            pairs_by_chain[chain] = {}
            continue
        addresses = [job["pool_address"] for job in chain_jobs
                     if cmc.is_contract_address(job["pool_address"])]
        merged: dict[str, dict] = {}
        for batch in _chunked(addresses, batch_size):
            if not batch:
                continue
            try:
                merged.update(fetch_pairs(network, batch, api_key=api_key))
            except RuntimeError as error:
                print(f"WARNING: snapshot fetch failed for {len(batch)} pools on "
                      f"chain {chain}: {error}", file=sys.stderr)
        pairs_by_chain[chain] = merged
    return pairs_by_chain


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover and collect DEX pool data for vault tokens.")
    parser.add_argument("--vaults", default=DEFAULT_VAULTS)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    api_key = resolve_api_key()
    if not api_key:
        print("ERROR: no CMC API key found. Create ~/.versusos/.env containing "
              "the line CMC_PRO_API_KEY=<your key> (free signup at "
              "https://pro.coinmarketcap.com), or export CMC_PRO_API_KEY.",
              file=sys.stderr)
        return 1

    options = load_json(args.config)
    try:
        vault_payload = load_json(args.vaults)
    except FileNotFoundError:
        print(f"ERROR: vault cache not found: {args.vaults}\n"
              "Run collect-vault first:  "
              "python skills/collect-vault/scripts/collect.py", file=sys.stderr)
        return 1

    seeds = discovery.vault_targets(vault_payload, options["chain_aliases"],
                                    gecko_aliases=options.get("gecko_aliases"))
    if not seeds:
        print("ERROR: no collectable vault tokens found in the vault cache "
              "(no underlyingTokens on supported chains).", file=sys.stderr)
        return 1

    whitelist_by_chain = {
        chain: {addr.lower() for addr in addrs}
        for chain, addrs in (options.get("counterparty_whitelist") or {}).items()}
    jobs, ds_pairs_by_chain = collect_discovery(
        seeds, whitelist_by_chain,
        throttle_seconds=options.get("ds_throttle_seconds", 0.0))
    if not jobs:
        print("ERROR: discovery found no USDC/USDT-paired pools; cache not "
              "written (existing cache preserved).", file=sys.stderr)
        return 1

    pairs_by_chain = collect_snapshots(
        jobs, api_key, batch_size=options.get("cmc_batch_size", 100),
        cmc_networks=options.get("cmc_networks"))
    snapshots = {
        (job["chain"], job["pool_address"], job["token_address"]):
            dexpools.build_snapshot(job, pairs_by_chain, ds_pairs_by_chain)
        for job in jobs}
    history_jobs = discovery.history_targets(
        jobs, snapshots, options["abnormal_price_delta"])
    selected = {(j["chain"], j["pool_address"], j["token_address"])
                for j in history_jobs}
    fetched_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload = dexpools.assemble(
        jobs, snapshots, history_days=options["history_days"],
        fetched_at=fetched_at, history_selected=selected,
        min_pool_liquidity=options.get("min_pool_liquidity", 0))
    counts = payload["counts"]
    if counts["persisted_pools"] == 0:
        print("ERROR: no score-relevant pools collected (no snapshots succeeded, "
              "or every discovered pool was below the liquidity floor and is not a "
              "history pool); cache not written (existing cache preserved).",
              file=sys.stderr)
        return 1
    write_cache(payload, args.out)
    print(f"Pools {counts['persisted_pools']}/{counts['qualifying_pools']} kept "
          f"({counts['dropped_unscored']} dropped as score-irrelevant) across "
          f"{counts['target_tokens']} targets, snapshots {counts['snapshot_ok']}, "
          f"history-selected {len(selected)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
