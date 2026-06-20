"""Out-of-coverage token naming for the inspect skill (thin Dexscreener client).

When a token CA matches no scored vault, the inspect SKILL calls this to name
the token (its symbol) so the out-of-coverage report can say what it is. Free,
keyless Dexscreener token-pairs endpoint; a custom User-Agent is required
(Dexscreener 403s the default urllib one). Returns None when the address is
unindexed or the lookup fails — the SKILL then reports "unidentified". This is
the only network-touching code in the skill. Run standalone:
    python scripts/naming.py --chain ethereum --token 0x...
"""
from __future__ import annotations

import argparse
import json
import urllib.request

TOKEN_PAIRS_URL = "https://api.dexscreener.com/token-pairs/v1/{chain}/{token}"
USER_AGENT = "versusos-inspect/1.0"


def fetch_token_symbol(chain, token_address, *, urlopen=None):
    """The token's symbol from Dexscreener token-pairs, or None.

    Reads the symbol from whichever side of a pair matches ``token_address``
    (case-insensitive). A blank input, any network/parse error, or an empty /
    non-list response -> None (the caller reports the token as unidentified).
    ``urlopen`` defaults to ``urllib.request.urlopen``; tests pass a fake that
    receives the built Request and returns a context manager whose ``.read()``
    yields JSON bytes.
    """
    if not chain or not token_address:
        return None
    target = token_address.lower()
    url = TOKEN_PAIRS_URL.format(chain=chain, token=token_address)
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=30.0) as response:
            pairs = json.loads(response.read())
    except Exception:
        return None
    if not isinstance(pairs, list):
        return None
    for pair in pairs:
        for side in ("baseToken", "quoteToken"):
            token = pair.get(side) or {}
            if (token.get("address") or "").lower() == target:
                return token.get("symbol")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Name a token by contract address.")
    parser.add_argument("--chain", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args(argv)
    symbol = fetch_token_symbol(args.chain, args.token)
    print(symbol if symbol else "unidentified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
