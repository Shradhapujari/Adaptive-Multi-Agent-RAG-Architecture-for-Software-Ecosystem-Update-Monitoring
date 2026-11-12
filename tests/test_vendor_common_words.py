"""
"Is it safe to update Firefox?" grounded to vendors ['firefox', 'safe'].

"safe" and "known" are real rows in /api/c/names, so whole-word matching made
ordinary question words into product filters. They now count as products only
when the question marks them as one: written in capitals ("SAFE") or followed
by a version ("safe 3.2"). Runs against the tracked catalog cache, offline.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grounding  # noqa: E402
from vendor import load_catalog  # noqa: E402

CATALOG = load_catalog(fetch=False)


@pytest.mark.parametrize("q, expected", [
    ("Is it safe to update Firefox?", ["firefox"]),
    ("Are there known issues with Chrome 130?", ["chrome"]),
    ("is it safe to install the latest chrome", ["chrome"]),
    ("Is SAFE 2.1 vulnerable?", ["safe"]),
    ("What changed in safe 3.2?", ["safe"]),
])
def test_common_words_need_product_context(q, expected):
    assert "safe" in CATALOG and "known" in CATALOG
    assert grounding.ground(q, catalog=CATALOG).vendor_names == expected
