import urllib.parse

import pytest

from core import geckoterminal
from dex_fakes import FakeUrlopen, http_error


def test_fetch_daily_ohlcv_builds_url_and_returns_candles():
    payload = {"data": {"attributes": {"ohlcv_list": [[1749513600, 1, 1, 1, 1, 1]]}}}
    urlopen = FakeUrlopen(payload)
    candles = geckoterminal.fetch_daily_ohlcv(
        "eth", "0xpool", days=180, token_address="0xtok", urlopen=urlopen)
    parsed = urllib.parse.urlparse(urlopen.requests[0].full_url)
    assert parsed.path == "/api/v2/networks/eth/pools/0xpool/ohlcv/day"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["limit"] == ["180"] and query["token"] == ["0xtok"]
    assert candles == [[1749513600, 1, 1, 1, 1, 1]]


def test_fetch_minute_ohlcv_builds_url():
    urlopen = FakeUrlopen({"data": {"attributes": {"ohlcv_list": []}}})
    geckoterminal.fetch_minute_ohlcv("eth", "0xp", minutes=720,
                                     token_address="0xt", urlopen=urlopen)
    parsed = urllib.parse.urlparse(urlopen.requests[0].full_url)
    assert parsed.path == "/api/v2/networks/eth/pools/0xp/ohlcv/minute"
    assert urllib.parse.parse_qs(parsed.query)["limit"] == ["720"]


def test_is_contract_address_accepts_plain_addresses_only():
    assert geckoterminal.is_contract_address("0x" + "a" * 40)
    assert geckoterminal.is_contract_address("0x3416CF6c708Da44DB2624D63ea0AAeF7113527C6")
    # 32-byte pool id (Uniswap v4) and Curve composite -> GeckoTerminal 404s on these.
    assert not geckoterminal.is_contract_address("0x" + "a" * 64)
    assert not geckoterminal.is_contract_address(
        "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7"
        "-0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
    assert not geckoterminal.is_contract_address("")
    assert not geckoterminal.is_contract_address(None)


def test_get_json_honors_retry_after_on_429(monkeypatch):
    slept = []
    monkeypatch.setattr(geckoterminal.time, "sleep", lambda s: slept.append(s))
    urlopen = FakeUrlopen({"data": {"attributes": {"ohlcv_list": []}}}, fail_times=1,
                          error=http_error(429, retry_after=7))
    geckoterminal.fetch_daily_ohlcv("eth", "0xp", days=180,
                                    token_address="0xt", urlopen=urlopen)
    assert urlopen.calls == 2 and slept == [7.0]


def test_get_json_raises_when_429_budget_exhausted(monkeypatch):
    monkeypatch.setattr(geckoterminal.time, "sleep", lambda s: None)
    urlopen = FakeUrlopen({}, fail_times=99, error=http_error(429, retry_after=1))
    with pytest.raises(RuntimeError, match="rate-limited"):
        geckoterminal.fetch_daily_ohlcv("eth", "0xp", days=180,
                                        token_address="0xt", urlopen=urlopen,
                                        rate_limit_retries=2)
    assert urlopen.calls == 3  # initial 429 + 2 rate-limit retries


def test_retry_after_seconds_parses_http_date():
    err = http_error(429, retry_after="Wed, 21 Oct 2015 07:28:00 GMT")
    assert geckoterminal._retry_after_seconds(err, default=5.0, cap=60.0) == 0.0
