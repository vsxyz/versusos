import json
import pathlib
import urllib.parse

from core import cmc
from dex_fakes import FakeUrlopen

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_fetch_pairs_batches_sends_key_and_lowercases():
    urlopen = FakeUrlopen(load_fixture("cmc_pair_quotes_sample.json"))
    requested = [
        "0x3416cf6c708da44db2624d63ea0aaef7113527c6",
        "0xaaaa000000000000000000000000000000000001",
        "0xbbbb000000000000000000000000000000000002",
    ]
    pairs = cmc.fetch_pairs("ethereum", requested, api_key="k", urlopen=urlopen)
    request = urlopen.requests[0]
    # urllib stores header names via str.capitalize().
    assert request.get_header("X-cmc_pro_api_key") == "k"
    parsed = urllib.parse.urlparse(request.full_url)
    assert parsed.path == "/v4/dex/pairs/quotes/latest"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["network_slug"] == ["ethereum"]
    assert query["contract_address"] == [",".join(requested)]
    assert query["aux"] == [cmc.AUX]
    assert query["skip_invalid"] == ["true"]
    # Response addresses are checksummed; keys must be lowercased.
    assert set(pairs) == {requested[0], requested[1]}
    assert pairs[requested[0]]["base_asset_symbol"] == "USDC"


def test_fetch_pairs_handles_null_data():
    urlopen = FakeUrlopen({"data": None, "status": {"error_code": "0"}})
    assert cmc.fetch_pairs("ethereum", ["0x01"], api_key="k", urlopen=urlopen) == {}


def test_fetch_pairs_empty_input_returns_empty_without_network():
    def urlopen(request, timeout=None):
        raise AssertionError("network must not be touched for an empty batch")

    assert cmc.fetch_pairs("ethereum", [], api_key="k", urlopen=urlopen) == {}


def test_is_contract_address_accepts_plain_addresses_only():
    assert cmc.is_contract_address("0x" + "a" * 40)
    # Checksummed (mixed-case) addresses are still valid.
    assert cmc.is_contract_address("0x3416CF6c708Da44DB2624D63ea0AAeF7113527C6")
    # 32-byte pool id (Uniswap v4), Curve composite, and junk are rejected —
    # CMC's contract_address param 400s on these.
    assert not cmc.is_contract_address("0x" + "a" * 64)
    assert not cmc.is_contract_address(
        "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7"
        "-0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        "-0xdac17f958d2ee523a2206206994597c13d831ec7")
    assert not cmc.is_contract_address("0x" + "a" * 39)  # too short
    assert not cmc.is_contract_address("a" * 40)         # no 0x prefix
    assert not cmc.is_contract_address("")
    assert not cmc.is_contract_address(None)
