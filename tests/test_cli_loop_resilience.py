"""
One bad question must not end the interactive session.

A question takes a 30s LLM round-trip and live fetches, so Ctrl-C mid-answer
and a source that 500s are both ordinary events during a live demo. Before
this, either one unwound straight out of `interactive()` -- KeyboardInterrupt
was caught only around `input()`, and nothing caught anything else -- so the
demo ended on a traceback and had to be restarted from a cold module load.

Offline: `run_demo` is replaced, so nothing reaches Ollama or the network.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag  # noqa: E402


def _feed(monkeypatch, lines):
    """Answer each input() call with the next line."""
    it = iter(lines)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


@pytest.mark.parametrize("boom", [KeyboardInterrupt, RuntimeError("ollama down")])
def test_failing_question_returns_to_the_prompt(monkeypatch, capsys, boom):
    asked = []

    def run_demo(q):
        asked.append(q)
        if len(asked) == 1:
            raise boom
        print("ANSWERED")

    monkeypatch.setattr(marag, "run_demo", run_demo)
    _feed(monkeypatch, ["first question", "second question", "exit"])

    marag.interactive()

    assert asked == ["first question", "second question"], "loop did not survive"
    assert "ANSWERED" in capsys.readouterr().out


def test_help_reprints_the_command_list(monkeypatch, capsys):
    _feed(monkeypatch, ["help", "exit"])
    marag.interactive()
    out = capsys.readouterr().out
    # once in the banner, once for the explicit 'help'
    assert out.count("'auto' — AUTO MODE") == 2


def test_exit_and_eof_both_leave(monkeypatch, capsys):
    monkeypatch.setattr(marag, "run_demo", lambda q: None)

    def eof(*a, **k):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    marag.interactive()
    assert "Goodbye!" in capsys.readouterr().out
