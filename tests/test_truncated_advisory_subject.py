"""/api/v/ advisory notes reach decide cut to 200 characters (app_1
fetch_release_notes). CVE-2026-115930 -- "The MongoDB Shell (mongosh) relies
on Node.js as a third-party runtime ..." -- loses its predicate ("prior to")
in the cut, the subject rule abstained, and a mongosh advisory counted for
"Latest Node.js version?" (live, 2026-11-12). With no predicate, the first
sentence is the subject."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decide

MONGOSH = ("The MongoDB Shell (mongosh) relies on Node.js as a third-party runtime that "
           "carries its own TLS root certificate store. This certificate store has the "
           "recoverable eMudhra intermediate CA certificates. This issue impacts MongoDB "
           "Shell (mongosh) versions prior to 2.14.0")


def _about(text, product="node.js"):
    d = {"doc_id": "n1", "source": "nvd", "text": text}
    return decide._about(d, decide._vendor_tokens([product]), set(), [], [product])


def test_runtime_named_in_a_truncated_subject_is_not_the_owner():
    assert not _about(MONGOSH[:200])
    assert not _about(MONGOSH)                     # untruncated, already rejected


def test_a_truncated_advisory_about_the_product_still_counts():
    assert _about("Node.js HTTP parser accepts malformed chunk extensions, letting an "
                  "attacker smuggle requests past a proxy that reads them differently")
    assert _about("In Node.js, the permission model lets a worker read files outside "
                  "the allowed paths when a symlink")
