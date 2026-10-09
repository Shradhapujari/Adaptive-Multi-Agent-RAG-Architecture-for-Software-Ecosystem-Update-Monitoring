"""The judge must say when a document has no body, not show a blank field.

Every google_news row is a bare headline (431/431 in run_1790126271), because
Google News RSS carries a title and an opaque redirect and nothing else. With
an empty `Content:` field those pairs disagreed with a second judge 43% of the
time, against 21% for documents that had a body -- the judge was grading its
own uncertainty about what had been withheld.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval_harness.judge import Judge


class _CapturingClient:
    """Stands in for the provider; keeps the prompt and returns a fixed grade."""

    def __init__(self):
        self.prompt = None

    def generate(self, prompt, **kw):
        self.prompt = prompt
        return '{"relevance": 1}'


def _judge():
    j = Judge.__new__(Judge)        # no provider, no network
    j.client = _CapturingClient()
    return j


def test_missing_body_is_named_not_blank():
    j = _judge()
    j.relevance_label("iOS 18 update option disappeared",
                      {"title": "iOS 27 Stuck on Update Requested?",
                       "text": "", "source": "google_news"})
    p = j.client.prompt
    assert "Content: (none" in p, "an absent body must be named"
    assert "headlines only" in p
    assert "Content: \n" not in p, "no blank Content field may reach the judge"


def test_whitespace_only_body_counts_as_missing():
    j = _judge()
    j.relevance_label("q", {"title": "t", "text": "   \n  ", "source": "local"})
    assert "Content: (none" in j.client.prompt


def test_real_body_is_passed_through_unchanged():
    j = _judge()
    j.relevance_label("q", {"title": "t", "text": "Both on latest system. "
                            "Update Requested then Update Failed.",
                            "source": "vendor_reddit"})
    p = j.client.prompt
    assert "Content: Both on latest system." in p
    assert "(none" not in p


def test_body_is_still_truncated():
    j = _judge()
    j.relevance_label("q", {"title": "t", "text": "x" * 900, "source": "vendor_reddit"})
    assert "x" * 600 in j.client.prompt
    assert "x" * 601 not in j.client.prompt
