import io
import json

import naming

USDC = "0xA0b86991c6218b36C1D19D4a2e9Eb0cE3606eB48"


def fake_urlopen(payload):
    def opener(request, timeout=None):
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def test_fetch_symbol_reads_the_matching_side():
    pairs = [{"baseToken": {"address": USDC, "symbol": "USDC"},
              "quoteToken": {"address": "0x" + "ab" * 20, "symbol": "WETH"}}]
    assert naming.fetch_token_symbol("ethereum", USDC, urlopen=fake_urlopen(pairs)) == "USDC"


def test_fetch_symbol_matches_quote_side_case_insensitively():
    pairs = [{"baseToken": {"address": "0x" + "cd" * 20, "symbol": "WETH"},
              "quoteToken": {"address": USDC.lower(), "symbol": "USDC"}}]
    assert naming.fetch_token_symbol("ethereum", USDC, urlopen=fake_urlopen(pairs)) == "USDC"


def test_fetch_symbol_none_when_empty():
    assert naming.fetch_token_symbol("ethereum", USDC, urlopen=fake_urlopen([])) is None


def test_fetch_symbol_none_on_network_error():
    def boom(request, timeout=None):
        raise RuntimeError("network down")
    assert naming.fetch_token_symbol("ethereum", USDC, urlopen=boom) is None


def test_fetch_symbol_none_on_blank_input():
    assert naming.fetch_token_symbol("", USDC, urlopen=fake_urlopen([])) is None
    assert naming.fetch_token_symbol("ethereum", "", urlopen=fake_urlopen([])) is None


def test_request_sets_custom_user_agent():
    captured = {}
    def capturing_opener(request, timeout=None):
        captured["ua"] = request.get_header("User-agent")
        return io.BytesIO(b"[]")
    naming.fetch_token_symbol("ethereum", USDC, urlopen=capturing_opener)
    assert captured["ua"] == naming.USER_AGENT
