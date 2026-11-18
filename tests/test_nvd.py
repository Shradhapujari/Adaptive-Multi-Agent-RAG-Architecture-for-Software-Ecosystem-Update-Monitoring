"""nvd.fetch: the API key goes in the apiKey header, and only when set."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nvd  # noqa: E402


class _R:
    status_code = 200

    def json(self):
        return {"totalResults": 0}


def _capture(seen):
    def get(url, params, timeout, **kw):
        seen.append(kw.get("headers"))
        return _R()
    return get


def test_the_key_is_sent_as_the_apikey_header(monkeypatch):
    monkeypatch.setenv("NVD_API_KEY", "test-key")
    seen = []
    nvd.fetch("chrome", get=_capture(seen))
    assert seen == [{"apiKey": "test-key"}]


def test_no_key_sends_no_header(monkeypatch):
    monkeypatch.delenv("NVD_API_KEY", raising=False)
    seen = []
    nvd.fetch("chrome", get=_capture(seen))
    assert seen == [None]
