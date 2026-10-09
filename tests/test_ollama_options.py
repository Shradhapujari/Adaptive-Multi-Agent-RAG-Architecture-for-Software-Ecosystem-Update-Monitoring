"""Every measured Ollama call pins keep_alive and num_ctx.

Ollama unloads an idle model after five minutes and reloads it on the next
call; in a judge pass that alternates models the reload lands in the latency
column as if the architecture had spent it. And an unstated num_ctx is whatever
the installed Ollama decides, so a future default change would silently change
a measurement. Both now travel in one shared payload builder.
"""

import io
import json
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tokens
from eval_harness.providers import OllamaClient
import multiagent_rag_v3 as marag


def test_shared_payload_carries_both_and_merges_options():
    p = tokens.ollama_payload("m", "hi", temperature=0.0, num_predict=40)
    assert p["keep_alive"] == -1
    assert p["options"] == {"num_ctx": 4096, "temperature": 0.0, "num_predict": 40}
    assert p["stream"] is False
    # a caller may override the shared context size
    assert tokens.ollama_payload("m", "hi", num_ctx=2048)["options"]["num_ctx"] == 2048


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(fn):
    """Run fn with urlopen stubbed; return the JSON body it posted."""
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data)
        return _Resp(json.dumps({"response": "ok", "prompt_eval_count": 1,
                                 "eval_count": 1}).encode())

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        fn()
    return sent["body"]


def test_provider_client_sends_them():
    body = _capture(lambda: OllamaClient("llama3.1")._generate("p", "sys", 0.0, 50))
    assert body["keep_alive"] == -1
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["num_predict"] == 50
    assert body["system"] == "sys"


def test_rewriter_call_sends_them():
    body = _capture(lambda: marag.call_llama("p"))
    assert body["keep_alive"] == -1
    assert body["options"] == {"num_ctx": 4096, "temperature": 0}
