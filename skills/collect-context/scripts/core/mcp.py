"""Minimal MCP client for the CMC MCP server (stdlib only, no registration).

Speaks JSON-RPC over streamable HTTP directly: one POST per tools/call. The
server is stateless for our calls (no initialize handshake, no session id —
live-verified 2026-06-11), and auth is the X-CMC-MCP-API-KEY header carrying
the same key as CMC_PRO_API_KEY. Self-contained on purpose: core/ is a
namespace package shared across skills, so this module must not collide with
collect-dex's core/http.py.
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "mcp.py is the MCP client imported by collect.py — it is not a "
        "standalone entrypoint and does nothing on its own.\n"
        "Run the collector instead:  python scripts/collect.py"
    )

import json
import time
import urllib.request

MCP_URL = "https://mcp.coinmarketcap.com/mcp"
USER_AGENT = "versusos-collect-context/1.0"


def call_tool(name: str, arguments: dict, *, api_key: str, urlopen=None,
              timeout: float = 30.0, retries: int = 3, backoff: float = 1.0):
    """POST one tools/call and return the tool's payload (parsed JSON).

    Raises RuntimeError after ``retries`` attempts, on a JSON-RPC error, or
    when the tool reports ``isError`` (its message is included).
    """
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(
        MCP_URL,
        data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
            "X-CMC-MCP-API-KEY": api_key,
        })
    last_error = None
    for attempt in range(retries):
        try:
            with opener(request, timeout=timeout) as response:
                body = json.loads(response.read())
            break
        except Exception as error:  # network / HTTP / JSON parse
            last_error = error
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    else:
        raise RuntimeError(
            f"MCP tools/call {name} failed after {retries} attempts: "
            f"{last_error}") from last_error

    if "error" in body:
        raise RuntimeError(f"MCP tools/call {name} returned a JSON-RPC "
                           f"error: {body['error'].get('message')}")
    result = body.get("result") or {}
    content = result.get("content") or [{}]
    text = content[0].get("text", "")
    if result.get("isError"):
        raise RuntimeError(f"MCP tool {name} errored: {text}")
    return json.loads(text)
