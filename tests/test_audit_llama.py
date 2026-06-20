import io
import json

from core import llama


def _fake_urlopen(payload):
    def opener(url, timeout=None):
        class Ctx:
            def __enter__(self):
                return io.BytesIO(json.dumps(payload).encode())
            def __exit__(self, *a):
                return False
        return Ctx()
    return opener


def test_fetch_audit_links_returns_links():
    opener = _fake_urlopen({"audit_links": ["https://a.com", "https://b.com"]})
    assert llama.fetch_audit_links("morpho-blue", urlopen=opener) == [
        "https://a.com", "https://b.com"]


def test_fetch_audit_links_missing_field_returns_empty():
    opener = _fake_urlopen({"name": "X"})
    assert llama.fetch_audit_links("x", urlopen=opener) == []


def test_fetch_audit_links_best_effort_on_error():
    def boom(url, timeout=None):
        raise OSError("network down")
    assert llama.fetch_audit_links("x", urlopen=boom) == []
