# Data Sources — collect-depeg-history

One source: **GeckoTerminal** public OHLCV API (keyless).

- **Daily (depeg):** `GET /api/v2/networks/{network}/pools/{address}/ohlcv/day`
  — up to `history_days` (≤180) candles, newest first.
- **Minute (dynamic):** `.../ohlcv/minute` — up to `minute_window_hours×60`
  (≤1000) candles in one call.
- **Orientation:** the `token` query param prices candles in the target token's
  USD regardless of base/quote order.
- **Pool address must be a plain contract address:** the endpoint addresses a
  pool by its `0x`+40-hex contract; Dexscreener `pairAddress` is sometimes a
  32-byte pool id (`0x`+64 hex, Uniswap v4) or a hyphen-joined Curve/registry
  composite, which 404 here. The collector skips those targets up front
  (`geckoterminal.is_contract_address`) rather than fetching and failing — there
  is no fallback OHLCV source, so the target simply gets no history (counted as
  `skipped_non_address`; the vault stays on its initial 0–100 score).
- **Rate limit:** **30 calls/min, keyless** (raised from 10 on 2023-04-19 — the
  official limit; verified at apiguide.geckoterminal.com). No per-second/burst
  limit and no `Retry-After` header are documented. Avoidance is layered:
  1. The collector throttles `throttle_seconds` (default **6.0s**) before **every**
     call — daily and minute alike, not just between pools — so a pool's two calls
     never fire as a burst. 6.0s ≈ **10 calls/min**, a third of the limit, leaving
     headroom even when a recent run's calls still sit in the 60-second window.
  2. **Resume:** pools already collected (both candle lists non-null) are reused,
     not re-fetched, so QA re-runs make far fewer calls. `--refresh` forces a full
     re-fetch.
  3. HTTP 429 is retried on a separate budget whose fallback backoff is sized to
     the 60-second window (`core/geckoterminal.py`), so a transient limit waits its
     window out and clears silently. A sustained limit can still leave a pool's
     candle list `null` after the budget — score then keeps that vault on its
     initial 0–100 score.
- **Why split from collect-dex:** fetching this for every target made collect-dex
  ~20 min. Restricting to the top-N finalists (default 10) keeps it to ~2–3 min at
  the conservative throttle.
