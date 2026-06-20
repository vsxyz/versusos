import json
import pathlib

from core import dexscreener
from dex_fakes import FakeUrlopen

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_fetch_token_pools_builds_url_and_returns_list():
    urlopen = FakeUrlopen(load_fixture("dexscreener_token_pairs_sample.json"))
    token = "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5"
    pools = dexscreener.fetch_token_pools("ethereum", token, urlopen=urlopen)
    assert urlopen.requests[0].full_url == (
        "https://api.dexscreener.com/token-pairs/v1/ethereum/" + token)
    assert isinstance(pools, list) and len(pools) == 4
    assert pools[0]["baseToken"]["symbol"] == "USD0"


def test_fetch_token_pools_non_list_response_is_empty():
    urlopen = FakeUrlopen({"error": "not found"})
    assert dexscreener.fetch_token_pools("ethereum", "0xabc", urlopen=urlopen) == []


def test_fetch_token_pools_empty_address_skips_network():
    def urlopen(request, timeout=None):
        raise AssertionError("network must not be touched for an empty address")
    assert dexscreener.fetch_token_pools("ethereum", "", urlopen=urlopen) == []
