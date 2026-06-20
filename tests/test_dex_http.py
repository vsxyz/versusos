import urllib.error

import pytest

from core import http
from dex_fakes import FakeResponse, FakeUrlopen, http_error


def test_get_json_sends_custom_user_agent():
    urlopen = FakeUrlopen({"ok": True})
    http.get_json("http://x", urlopen=urlopen)
    request = urlopen.requests[0]
    assert request.get_header("User-agent") == http.USER_AGENT
    assert request.full_url == "http://x"


def test_get_json_retries_then_succeeds():
    urlopen = FakeUrlopen({"ok": True}, fail_times=2)
    result = http.get_json("http://x", urlopen=urlopen, retries=3, backoff=0)
    assert result == {"ok": True}
    assert urlopen.calls == 3


def test_get_json_raises_after_exhausting_retries():
    urlopen = FakeUrlopen({"ok": True}, fail_times=99)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        http.get_json("http://x", urlopen=urlopen, retries=3, backoff=0)
    assert urlopen.calls == 3


def test_get_json_retries_http_errors():
    inner = FakeUrlopen({"ok": True})
    calls = {"count": 0}

    def urlopen(request, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                "http://x", 429, "Too Many Requests", None, None
            )
        return inner(request, timeout=timeout)

    result = http.get_json("http://x", urlopen=urlopen, retries=3, backoff=0,
                           rate_limit_backoff=0)
    assert result == {"ok": True}
    assert calls["count"] == 2


def test_get_json_non_json_body_raises_after_retries():
    calls = {"count": 0}

    def urlopen(request, timeout=None):
        calls["count"] += 1
        return FakeResponse(b"<html>nope</html>")

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        http.get_json("http://x", urlopen=urlopen, retries=3, backoff=0)
    assert calls["count"] == 3


def test_get_json_merges_extra_headers():
    urlopen = FakeUrlopen({"ok": True})
    http.get_json("http://x", headers={"X-CMC_PRO_API_KEY": "k"}, urlopen=urlopen)
    request = urlopen.requests[0]
    # urllib stores header names via str.capitalize().
    assert request.get_header("X-cmc_pro_api_key") == "k"
    assert request.get_header("User-agent") == http.USER_AGENT


def test_get_json_honors_retry_after_on_429(monkeypatch):
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    urlopen = FakeUrlopen({"ok": True}, fail_times=1,
                          error=http_error(429, retry_after=7))
    assert http.get_json("http://x", urlopen=urlopen) == {"ok": True}
    assert urlopen.calls == 2
    assert slept == [7.0]  # waited the server's Retry-After, not the blind backoff


def test_get_json_429_uses_separate_retry_budget(monkeypatch):
    # 4 consecutive 429s exceed the transient retries=3 budget but fall within
    # the dedicated 429 budget, so the call still succeeds.
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    urlopen = FakeUrlopen({"ok": True}, fail_times=4,
                          error=http_error(429, retry_after=1))
    result = http.get_json("http://x", urlopen=urlopen, retries=3,
                           rate_limit_retries=5)
    assert result == {"ok": True}
    assert urlopen.calls == 5


def test_get_json_raises_when_429_budget_exhausted(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    urlopen = FakeUrlopen({"ok": True}, fail_times=99,
                          error=http_error(429, retry_after=1))
    with pytest.raises(RuntimeError, match="rate-limited"):
        http.get_json("http://x", urlopen=urlopen, rate_limit_retries=3)
    assert urlopen.calls == 4  # initial 429 + 3 rate-limit retries


def test_get_json_caps_retry_after_on_429(monkeypatch):
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    urlopen = FakeUrlopen({"ok": True}, fail_times=1,
                          error=http_error(429, retry_after=9999))
    http.get_json("http://x", urlopen=urlopen, rate_limit_cap=60.0)
    assert slept == [60.0]  # a hostile/huge Retry-After is clamped to the cap


def test_get_json_429_without_header_escalates_backoff(monkeypatch):
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    urlopen = FakeUrlopen({"ok": True}, fail_times=2,
                          error=http_error(429))  # no Retry-After header
    http.get_json("http://x", urlopen=urlopen, rate_limit_backoff=5.0)
    assert urlopen.calls == 3
    assert slept == [5.0, 10.0]  # rate_limit_backoff * 2**n


def test_retry_after_seconds_parses_http_date(monkeypatch):
    # HTTP-date form; a past date yields 0 (deterministic, no now() coupling)
    err = http_error(429, retry_after="Wed, 21 Oct 2015 07:28:00 GMT")
    assert http._retry_after_seconds(err, default=5.0, cap=60.0) == 0.0
