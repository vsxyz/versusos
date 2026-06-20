"""Shared test fakes for the collect-dex client tests (not a test module).

These mirror the contract of ``core.http.get_json``: it builds a
``urllib.request.Request`` and passes that to the opener, so ``FakeUrlopen``
receives a Request object (assert on URL via ``request.full_url``).
"""
import email.message
import json
import urllib.error


def http_error(code, *, retry_after=None):
    """A ``urllib.error.HTTPError``, optionally carrying a Retry-After header.

    Lets the client tests exercise ``core.http.get_json``'s 429 handling
    (retry_after may be a delta-seconds int or an HTTP-date string).
    """
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


class FakeResponse:
    """Context-manager response exposing read() -> JSON bytes (like urlopen)."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class FakeUrlopen:
    """Callable stand-in for urllib.request.urlopen.

    Receives the urllib.request.Request object http.get_json builds; records it
    so tests can assert on URL and headers. Optionally raises on the first
    ``fail_times`` calls — ``error`` (default ConnectionError) is the exception
    raised, e.g. ``http_error(429, retry_after=7)``.
    """

    def __init__(self, data, fail_times=0, error=None):
        self._payload = json.dumps(data).encode()
        self._fail_times = fail_times
        self._error = error
        self.calls = 0
        self.requests = []

    def __call__(self, request, timeout=None):
        self.calls += 1
        self.requests.append(request)
        if self.calls <= self._fail_times:
            raise self._error or ConnectionError("boom")
        return FakeResponse(self._payload)
