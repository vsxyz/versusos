import json
import pathlib

import pytest

from core import defillama

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


class _FakeResponse:
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

    Returns mapped JSON; optionally raises on the first ``fail_times`` calls.
    """

    def __init__(self, data, fail_times=0):
        self._payload = json.dumps(data).encode()
        self._fail_times = fail_times
        self.calls = 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ConnectionError("boom")
        return _FakeResponse(self._payload)


def test_fetch_vaults_returns_data_list():
    urlopen = FakeUrlopen(load_fixture("defillama_vaults_sample.json"))
    vaults = defillama.fetch_vaults(urlopen=urlopen)
    assert len(vaults) == 10
    assert vaults[0]["pool"] == "p1"


def test_get_json_retries_then_succeeds():
    urlopen = FakeUrlopen({"ok": True}, fail_times=2)
    result = defillama._get_json("http://x", urlopen=urlopen, retries=3, backoff=0)
    assert result == {"ok": True}
    assert urlopen.calls == 3


def test_get_json_raises_after_exhausting_retries():
    urlopen = FakeUrlopen({"ok": True}, fail_times=99)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        defillama._get_json("http://x", urlopen=urlopen, retries=3, backoff=0)
    assert urlopen.calls == 3


def test_fetch_hacks_returns_list():
    # /hacks returns a top-level LIST (not {"data": [...]})
    urlopen = FakeUrlopen([{"name": "X", "defillamaId": 1}, {"name": "Y"}])
    hacks = defillama.fetch_hacks(urlopen=urlopen)
    assert isinstance(hacks, list)
    assert len(hacks) == 2
    assert hacks[0]["defillamaId"] == 1


def test_fetch_protocols_returns_list():
    urlopen = FakeUrlopen([{"slug": "aave-v3", "id": "1599", "parentProtocol": "parent#aave"}])
    protocols = defillama.fetch_protocols(urlopen=urlopen)
    assert isinstance(protocols, list)
    assert protocols[0]["slug"] == "aave-v3"
