"""Pure, network-free token-CA -> scored-vault matching for the inspect skill.

Resolves a user-supplied token contract address to the stablecoin vaults that
use it as an underlying, by matching the address against the collect-vault
cache's ``underlyingTokens`` and joining the matched ``pool`` ids to the score
cache's records. No network and no I/O: every input is a plain dict from the
caches, so this is unit-tested against tests/fixtures/.
"""
from __future__ import annotations

import re

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$", re.IGNORECASE)


def is_evm_address(value) -> bool:
    """True only for a plain EVM contract address (``0x`` + 40 hex).

    Duplicated from score/collect-dex (skills are self-contained, never import
    each other). Used to reject non-EVM CAs (e.g. Solana base58) — v1 is EVM-only.
    """
    return bool(value and _ADDRESS_RE.match(value))


def _rank_key(record):
    """Safety rank: ``normalized_score`` desc, ``tvlUsd`` desc as the tiebreak.

    Mirrors recommend's tie rule (higher safety first; the larger vault breaks
    ties). Missing fields sort as 0 so an unscored match sinks to the bottom.
    """
    return (record.get("normalized_score") or 0, record.get("tvlUsd") or 0)


def match_token(addresses, vault_payload, score_payload, *, chain=None):
    """Scored vaults whose ``underlyingTokens`` include any of ``addresses``.

    ``addresses``: iterable of EVM contract addresses (any case).
    ``vault_payload``: the collect-vault cache dict (``vaults`` with ``pool``,
    ``chain``, ``underlyingTokens``).
    ``score_payload``: the score cache dict (``scores`` keyed by ``pool``).
    ``chain``: optional case-insensitive filter on each vault's ``chain``.

    Returns the matched score records (each augmented with ``scored: True``),
    safety-ranked. A matched vault absent from the score cache is returned as a
    minimal ``{pool, project, chain, symbol, tvlUsd, scored: False}`` record so
    the caller can report it without inventing a score.
    """
    targets = {a.lower() for a in addresses if a and is_evm_address(a)}
    if not targets:
        return []
    chain_filter = chain.lower() if chain else None
    score_by_pool = {s.get("pool"): s for s in score_payload.get("scores") or []}
    matched = []
    for vault in vault_payload.get("vaults") or []:
        if chain_filter and (vault.get("chain") or "").lower() != chain_filter:
            continue
        tokens = {(t or "").lower() for t in vault.get("underlyingTokens") or []}
        if not targets & tokens:
            continue
        record = score_by_pool.get(vault.get("pool"))
        if record is None:
            matched.append({"pool": vault.get("pool"), "project": vault.get("project"),
                            "chain": vault.get("chain"), "symbol": vault.get("symbol"),
                            "tvlUsd": vault.get("tvlUsd"), "scored": False})
        else:
            matched.append({**record, "scored": True})
    matched.sort(key=_rank_key, reverse=True)
    return matched


if __name__ == "__main__":
    raise SystemExit(
        "matching.py provides pure matching helpers imported by resolve.py — "
        "it is not a standalone entrypoint and does nothing on its own.\n"
        "Run the resolver instead:  python scripts/resolve.py --addresses 0x..."
    )
