"""The console declines a question that names no product and carries no
software intent, before any fetch: "What's the weather in Paris?" was answered
with an OpenSearch advisory and a "safe" verdict at confidence 0.6."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app_1
import grounding

OFF_TOPIC = ["What's the weather in Paris?", "Who won the World Cup?",
             "Write me a poem about cats", "How do I bake bread?",
             "What is the capital of France?", "tell me a joke"]
ON_TOPIC = ["Is it safe to update Firefox?", "Any critical Linux updates today?",
            "Security patches released in the past 7 days",
            "Critical software updates published today",
            "MacOS updates with negative community reaction",
            "What bugs were fixed in Chrome recently?",
            "Latest Djnago version?"]          # a typo is handled downstream


@pytest.mark.parametrize("q", OFF_TOPIC)
def test_off_topic_is_declined(q):
    assert app_1._off_topic_note(q), q


@pytest.mark.parametrize("q", ON_TOPIC)
def test_software_questions_pass(q):
    assert app_1._off_topic_note(q) is None, q


@pytest.mark.parametrize("q,word", [("What's the weather in Paris?", "weather"),
                                    ("Is it safe to update Firefox?", "safe"),
                                    ("MacOS updates with negative community reaction", "community")])
def test_common_words_are_not_products(q, word):
    assert word not in grounding.ground(q).vendor_names
