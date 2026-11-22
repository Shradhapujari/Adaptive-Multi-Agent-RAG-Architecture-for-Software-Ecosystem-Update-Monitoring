"""MARAG_SYNTH_MODEL picks the model marag's Evaluator synthesises with."""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _restore_default():
    yield
    os.environ.pop("MARAG_SYNTH_MODEL", None)
    import multiagent_rag_v3
    importlib.reload(multiagent_rag_v3)          # later tests see the default


def _synth_model(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("MARAG_SYNTH_MODEL", raising=False)
    else:
        monkeypatch.setenv("MARAG_SYNTH_MODEL", value)
    import multiagent_rag_v3
    return importlib.reload(multiagent_rag_v3).SYNTH_MODEL


def test_default_is_mistral(monkeypatch):
    assert _synth_model(monkeypatch, None) == "mistral"
    assert _synth_model(monkeypatch, "  ") == "mistral"


def test_env_overrides_it(monkeypatch):
    assert _synth_model(monkeypatch, "llama3.1") == "llama3.1"


def test_the_run_gate_records_it(monkeypatch):
    from eval_harness import preflight
    monkeypatch.setenv("MARAG_SYNTH_MODEL", "llama3.1")
    assert preflight.marag_env()["MARAG_SYNTH_MODEL"] == "llama3.1"
