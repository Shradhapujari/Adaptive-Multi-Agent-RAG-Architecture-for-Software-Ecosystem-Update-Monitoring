"""A Gemini response carrying no text must raise, not return "".

The 2.5 models think by default and thinking tokens count against
max_output_tokens, so a budget that is merely too small comes back with
finish_reason=MAX_TOKENS and no text part. Returning "" there would score a
configuration mistake as the model answering with nothing.

These exercise the pure reader, so they run without google-genai installed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from eval_harness.providers import GeminiClient


class _Cand:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, text=None, finish_reason=None, raises=False):
        self._text, self._raises = text, raises
        self.candidates = [_Cand(finish_reason)] if finish_reason else []

    @property
    def text(self):
        if self._raises:
            raise ValueError("no Part to return")
        return self._text


def test_text_is_returned_when_present():
    assert GeminiClient._text_or_raise(_Resp(text="hello")) == "hello"


def test_truncated_response_raises_naming_the_finish_reason():
    with pytest.raises(ValueError) as e:
        GeminiClient._text_or_raise(_Resp(text=None, finish_reason="MAX_TOKENS"))
    assert "MAX_TOKENS" in str(e.value)
    assert "max_output_tokens" in str(e.value)


def test_sdk_that_raises_on_text_is_reported_not_swallowed():
    """Some SDK versions raise from .text rather than returning None."""
    with pytest.raises(ValueError) as e:
        GeminiClient._text_or_raise(_Resp(raises=True, finish_reason="SAFETY"))
    assert "SAFETY" in str(e.value)


def test_empty_response_with_no_candidates_still_raises():
    with pytest.raises(ValueError):
        GeminiClient._text_or_raise(_Resp(text=""))


def test_generate_surfaces_it_as_llm_error():
    """generate() wraps _generate's exceptions, so the harness sees LLMError
    naming the spec rather than an empty string it would score."""
    from eval_harness.providers import LLMError

    client = GeminiClient("gemini-2.5-flash")
    client._generate = lambda *a, **k: GeminiClient._text_or_raise(
        _Resp(text=None, finish_reason="MAX_TOKENS"))
    with pytest.raises(LLMError) as e:
        client.generate("anything")
    assert "gemini:gemini-2.5-flash" in str(e.value)
