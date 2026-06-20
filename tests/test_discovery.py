import json
import pathlib

from core import discovery

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


CHAIN_ALIASES = {"ethereum": "ethereum"}
GECKO_ALIASES = {"ethereum": "eth"}


def test_vault_targets_dedups_lowercases_and_skips_unknown_chains():
    seeds = discovery.vault_targets(
        load_fixture("dex_seed_vaults_sample.json"), CHAIN_ALIASES,
        gecko_aliases=GECKO_ALIASES)
    # USD0 + USDC (the two ethereum addresses); USDC appears twice -> one seed;
    # the Solana vault is skipped (chain absent from chain_aliases).
    assert seeds == [
        {"chain": "ethereum",
         "token_address": "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5",
         "network": "ethereum", "gecko_network": "eth"},
        {"chain": "ethereum",
         "token_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
         "network": "ethereum", "gecko_network": "eth"},
    ]


def test_vault_targets_gecko_network_defaults_to_none():
    seeds = discovery.vault_targets(
        load_fixture("dex_seed_vaults_sample.json"), CHAIN_ALIASES)
    assert seeds[0]["gecko_network"] is None


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USD0 = "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5"

# Valid plain (0x + 40 hex) pool addresses for history-selection tests.
POOL_A = "0x" + "a" * 40
POOL_B = "0x" + "b" * 40
POOL_C = "0x" + "c" * 40


def _usd0_seed():
    return {"chain": "ethereum", "token_address": USD0,
            "network": "ethereum", "gecko_network": "eth"}


def test_pools_from_token_pairs_keeps_only_whitelisted_counterparties():
    pairs = load_fixture("dexscreener_token_pairs_sample.json")
    jobs, ds_pairs = discovery.pools_from_token_pairs(
        pairs, _usd0_seed(), {USDC, USDT})
    # USD0/USDC (base), USD0/USDT (base), USDT/USD0 (target on quote) kept;
    # bUSD0/USD0 dropped (counterparty bUSD0 not whitelisted).
    addrs = {job["pool_address"] for job in jobs}
    assert addrs == {
        "0xcccc000000000000000000000000000000000001",
        "0xcccc000000000000000000000000000000000002",
        "0xcccc000000000000000000000000000000000004",
    }
    assert "0xcccc000000000000000000000000000000000003" not in ds_pairs


def test_pools_from_token_pairs_symbol_and_target_orientation():
    pairs = load_fixture("dexscreener_token_pairs_sample.json")
    jobs, _ = discovery.pools_from_token_pairs(pairs, _usd0_seed(), {USDC, USDT})
    by_addr = {job["pool_address"]: job for job in jobs}
    base_job = by_addr["0xcccc000000000000000000000000000000000001"]
    assert base_job["symbol"] == "USD0"          # target symbol from the matched side
    assert base_job["token_address"] == USD0
    assert base_job["dex"] == "uniswap"
    assert base_job["network"] == "ethereum" and base_job["gecko_network"] == "eth"
    quote_job = by_addr["0xcccc000000000000000000000000000000000004"]
    assert quote_job["symbol"] == "USD0"         # target is the quote side here


def _job(pool, token=USD0, chain="ethereum"):
    return {"symbol": "USD0", "chain": chain, "dex": "x", "pool_address": pool,
            "token_address": token, "network": "ethereum", "gecko_network": "eth"}


def _snap(liq, price=1.0):
    return {"liquidity_usd": liq, "price_usd": price}


def test_history_targets_picks_most_liquid_price_sane_pool_per_target():
    jobs = [_job(POOL_A), _job(POOL_B), _job(POOL_C)]
    snapshots = {
        ("ethereum", POOL_A, USD0): _snap(500000),
        ("ethereum", POOL_B, USD0): _snap(2000000),          # most liquid
        ("ethereum", POOL_C, USD0): _snap(9000000, price=2.0),  # abnormal -> excluded
    }
    picked = discovery.history_targets(jobs, snapshots, abnormal_price_delta=0.5)
    assert [j["pool_address"] for j in picked] == [POOL_B]


def test_history_targets_separate_pick_per_target_token():
    jobs = [_job(POOL_A, token=USD0), _job(POOL_B, token=USDC)]
    snapshots = {
        ("ethereum", POOL_A, USD0): _snap(100000),
        ("ethereum", POOL_B, USDC): _snap(100000),
    }
    picked = discovery.history_targets(jobs, snapshots, abnormal_price_delta=0.5)
    assert {j["pool_address"] for j in picked} == {POOL_A, POOL_B}


def test_history_targets_skips_targets_with_no_eligible_pool():
    jobs = [_job(POOL_A)]
    snapshots = {("ethereum", POOL_A, USD0): None}
    assert discovery.history_targets(jobs, snapshots, abnormal_price_delta=0.5) == []


def test_history_targets_excludes_non_contract_pool_address():
    # The most-liquid pools are a Uniswap-v4 pool id and a Curve composite, which
    # GeckoTerminal cannot fetch; the history pool must be the lower-liquidity
    # plain-contract-address pool so collect-depeg-history can fetch its OHLCV.
    v4_id = "0x" + "d" * 64
    composite = f"{USDC}-{USDT}"
    jobs = [_job(v4_id), _job(composite), _job(POOL_A)]
    snapshots = {
        ("ethereum", v4_id, USD0): _snap(9000000),      # most liquid, not a contract
        ("ethereum", composite, USD0): _snap(8000000),  # not a contract
        ("ethereum", POOL_A, USD0): _snap(100000),      # fetchable -> selected
    }
    picked = discovery.history_targets(jobs, snapshots, abnormal_price_delta=0.5)
    assert [j["pool_address"] for j in picked] == [POOL_A]
