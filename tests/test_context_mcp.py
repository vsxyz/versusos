import json

import pytest

from core import mcp
from dex_fakes import FakeUrlopen


def envelope(payload, *, is_error=False):
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}],
                       "isError": is_error}}


def test_call_tool_posts_jsonrpc_with_key_and_returns_payload():
    urlopen = FakeUrlopen(envelope({"ok": 1}))
    payload = mcp.call_tool("get_global_metrics_latest", {}, api_key="k",
                            urlopen=urlopen)
    assert payload == {"ok": 1}
    request = urlopen.requests[0]
    assert request.full_url == mcp.MCP_URL
    # urllib stores header names via str.capitalize().
    assert request.get_header("X-cmc-mcp-api-key") == "k"
    assert request.get_header("Content-type") == "application/json"
    body = json.loads(request.data)
    assert body["method"] == "tools/call"
    assert body["params"] == {"name": "get_global_metrics_latest",
                              "arguments": {}}


def test_call_tool_raises_on_tool_error():
    urlopen = FakeUrlopen(envelope({"error": "id: Required"}, is_error=True))
    with pytest.raises(RuntimeError, match="get_crypto_latest_news"):
        mcp.call_tool("get_crypto_latest_news", {}, api_key="k",
                      urlopen=urlopen)


def test_call_tool_raises_on_rpc_error():
    urlopen = FakeUrlopen({"jsonrpc": "2.0", "id": 1,
                           "error": {"code": -32600, "message": "bad"}})
    with pytest.raises(RuntimeError, match="bad"):
        mcp.call_tool("search_cryptos", {"query": "USDC"}, api_key="k",
                      urlopen=urlopen)


def test_call_tool_retries_then_succeeds():
    urlopen = FakeUrlopen(envelope([1, 2]), fail_times=2)
    payload = mcp.call_tool("search_cryptos", {"query": "USDC"}, api_key="k",
                            urlopen=urlopen, retries=3, backoff=0)
    assert payload == [1, 2]
    assert urlopen.calls == 3
