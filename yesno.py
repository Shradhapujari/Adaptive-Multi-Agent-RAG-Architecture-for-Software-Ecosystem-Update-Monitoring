"""
Yes/No consensus over a thread's comments.

A large share of the update questions in the lake are answerable with one
word: "did the latest Fedora 44 update delete your kernel and grub?" does not
want a synthesised paragraph, it wants a count of how many other people had it
happen. The retrieval pipeline already finds the thread; this module reads the
thread's own comments and tallies them.

Rule-based on purpose. The deployed Streamlit host has no Ollama and may hold
no API key (see answer_agent), and a stance tally that silently degrades to
"unclear" everywhere on the host the demo actually runs on is not a feature.
The markers below are literal phrases people use to answer this kind of
question, so the classifier is auditable: every count can be traced to the
comment and the phrase that produced it.

One vote per author, and the asker is never counted among the answers -- the
question is theirs, their own follow-ups are the report being checked, not a
confirmation of it. They are reported separately instead.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

__all__ = ["looks_yesno", "stance", "tally", "verdict_line", "fetch_thread",
           "find_thread"]

THREAD_API = "https://releasetrain.io/api/reddit/"
QUESTIONS_API = "https://releasetrain.io/api/reddit/query/questions"

# An auxiliary opener, or the "anyone else" that carries the same shape. Real
# posts rarely open on the auxiliary -- "guys did the latest update..." -- so a
# few words of address are allowed in front of it. A wh-word opener is not a
# yes/no question however it continues ("what version is this"), so it is cut
# first.
# The auxiliary has to open the text, after at most two of the ways people
# address a forum before asking. The first version allowed any three words
# there so that "guys did the latest update..." would match; measured over the
# frozen 50-question feed (scripts/eval_yesno.py) that slack was half the
# flags, because it also matches a declarative whose subject precedes its verb
# -- "I have taken over responsibility...", "W32tm is making me lose my sleep"
# -- and two of those went on to report a head-count for a troubleshooting
# post, which is the worst thing this module can do.
#
# Scanning every sentence of the body instead was tried and measured worse
# still (precision 0.50 -> 0.40): a long help post nearly always contains some
# sentence that opens on an auxiliary.
#
# `(?![\w'])` is what stops `can` matching `can't` -- the apostrophe ends the
# word, so every "Can't set Firefox as default" title used to read as a
# question.
_WH = r"(?:what|which|how|why|when|where|who|whose)"
_FILLER = (r"(?:guys|hey|hi|hello|folks|everyone|all|so|ok|okay|well|also|but|"
           r"and|edit|ps|quick\s+question|question)[,:]?\s+")
_AUX = (r"(?:did|does|do|is|are|was|were|has|have|had|can|could|will|would|"
        r"should|any\s?(?:one|body)(?:\s+else)?)")

_WH_RE = re.compile(rf"^\s*{_WH}\b", re.I)
_HAS_WH = re.compile(rf"\b{_WH}\b", re.I)
_YESNO_RE = re.compile(rf"^\s*(?:{_FILLER}){{0,2}}{_AUX}(?![\w'])", re.I)

# Checked in this order: a "no" phrase wins over a "yes" phrase in the same
# comment, because the no-phrases are negations ("never had the same issue"
# contains "same issue") and the yes-phrases are not.
NO_MARKERS = (
    "never had", "never heard", "never seen", "never experienced", "never happened",
    "no issue", "no issues", "no problem", "no problems", "not had", "haven't had",
    "havent had", "have not had", "not seen", "hasn't happened", "didn't happen",
    "did not happen", "works fine", "working fine", "runs fine", "no such",
    "mine is fine", "all fine", "nope", "not for me", "no, ", "no.",
)
YES_MARKERS = (
    "same here", "same issue", "same problem", "same thing", "same boat",
    "me too", "happened to me", "happened here", "i had this", "i have this",
    "can confirm", "confirmed", "yes, ", "yes.", "yep", "yeah", "affected me",
    "had to reinstall", "broke mine", "same for me",
)

# Bots and removed comments are not people with an opinion.
_SKIP_AUTHORS = {"automoderator", "[deleted]", "[removed]", ""}


def looks_yesno(question: str, is_title: bool = False) -> bool:
    """True when the question is phrased to be answerable yes or no.

    `is_title` adds the one rule that holds for titles only: a title ending in
    a question mark with no wh-word in it is a yes/no question whatever its
    verb ("No more synced groups for snapcast clients?"). Bodies are excluded
    from it because a body's trailing fragment ("Especially the Samsung
    ecosystem with it?") is a continuation of the post, not its question.
    """
    q = (question or "").strip()
    if not q:
        return False
    if is_title and q.endswith("?") and not _HAS_WH.search(q):
        return True
    return not _WH_RE.match(q) and bool(_YESNO_RE.match(q))


def stance(text: str) -> str:
    """One comment's answer to the question: yes | no | unclear."""
    t = " " + re.sub(r"\s+", " ", (text or "").lower()).strip() + " "
    for m in NO_MARKERS:
        if m in t:
            return "no"
    for m in YES_MARKERS:
        if m in t:
            return "yes"
    return "unclear"


def tally(thread: dict, unclear_as_no: bool = False) -> dict:
    """Count yes/no/unclear across a thread's commenters, one vote per author.

    Returns the votes themselves alongside the counts: the phrase that decided
    each vote is what makes the number checkable, so the UI can show it.

    `unclear_as_no` reads a commenter who neither confirms nor denies as a no.
    For "did this happen to you?" the reading is defensible -- someone who had
    their kernel deleted says so -- but it is a claim about silence, not
    something the comment says, so it is off by default and the app exposes it
    as a switch rather than a constant. The unclear votes are kept either way,
    so the count remains traceable to the comments that produced it.
    """
    asker = (thread.get("author") or "").lower()
    votes: Dict[str, dict] = {}
    for c in thread.get("comments") or []:
        author = (c.get("author") or "").strip()
        key = author.lower()
        if key in _SKIP_AUTHORS or key == asker or c.get("is_submitter"):
            continue
        s = stance(c.get("body", ""))
        prev = votes.get(key)
        # An author who says something substantive later outranks their own
        # earlier "What?" -- first *classifiable* comment wins, not first.
        if prev is None or (prev["stance"] == "unclear" and s != "unclear"):
            votes[key] = {"author": author, "stance": s,
                          "body": c.get("body", ""),
                          "url": c.get("permalink", "")}
    counts = {"yes": 0, "no": 0, "unclear": 0}
    for v in votes.values():
        counts[v["stance"]] += 1
    if unclear_as_no:
        counts["no"] += counts["unclear"]
    asker_says = next((c.get("body", "") for c in thread.get("comments") or []
                       if c.get("is_submitter")), "")
    return {**counts, "votes": list(votes.values()), "asker_report": asker_says,
            "answered": counts["yes"] + counts["no"],
            "unclear_as_no": unclear_as_no}


def verdict_line(t: dict) -> str:
    """The one-line answer, or an honest refusal to call it."""
    if not t["answered"]:
        return f"No answer in the comments — {t['unclear']} commenter(s), none confirming or denying."
    call = "Yes" if t["yes"] > t["no"] else "No" if t["no"] > t["yes"] else "Split"
    if not t["unclear"]:
        tail = ""
    elif t.get("unclear_as_no"):
        # They are already inside the "no" count; saying so keeps the number
        # honest about where it came from.
        tail = f" · {t['unclear']} of the no's are non-committal comments"
    else:
        tail = f" · {t['unclear']} unclear"
    return f"{call} — No ({t['no']} users) · Yes ({t['yes']} users){tail}"


def fetch_thread(reddit_id: str, timeout: int = 10) -> Optional[dict]:
    """Pull one thread with its comments from the lake."""
    import requests
    try:
        r = requests.get(THREAD_API + str(reddit_id), timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def find_thread(question: str, pool: int = 100, timeout: int = 20) -> Optional[dict]:
    """The lake's question thread that best matches `question`, comments and all.

    The questions feed is where yes/no questions live and it returns each
    thread's comments inline, so one call is the whole retrieval. Its own `q`
    parameter does not narrow the feed much, so the pool is ranked here --
    with the same BM25 reranker the pipeline uses elsewhere, rather than a
    second scoring rule that could disagree with it.
    """
    import requests
    try:
        r = requests.get(QUESTIONS_API, params={"where": "either", "limit": pool},
                         timeout=timeout)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception:
        return None
    if not rows:
        return None
    from rerank import BM25Reranker
    # `detail` is what the reranker reads alongside the title; on this feed the
    # body of the post lives in author_description.
    for row in rows:
        row.setdefault("detail", row.get("author_description", ""))
    best = BM25Reranker().rank(question, rows, top_k=1)
    return best[0] if best else None


def _demo() -> None:
    # Real comments from reddit 1w0n4ik, the thread this module was built on.
    thread = {
        "author": "One-Stress9309",
        "comments": [
            {"author": "PixelBrush6584", "body": "What?", "is_submitter": False},
            {"author": "AardvarkSad7634", "is_submitter": False,
             "body": "Sounds aweful. Oh well, glad I'm using Silverblue"},
            {"author": "Available-Hat476", "is_submitter": False,
             "body": "Eh? Never heard of this problem and never had it. Been running Fedora for years now on several computers."},
            {"author": "One-Stress9309", "body": "i had to reinstall", "is_submitter": True},
            {"author": "paulshriner", "is_submitter": False,
             "body": "I've never had a Fedora update delete my kernel and grub and I have not heard of this happening as of now."},
        ],
    }
    t = tally(thread)
    assert t["yes"] == 0 and t["no"] == 2 and t["unclear"] == 2, t
    assert t["asker_report"] == "i had to reinstall"          # OP not counted as a yes
    assert verdict_line(t).startswith("No — No (2 users) · Yes (0 users)"), verdict_line(t)
    strict = tally(thread, unclear_as_no=True)
    assert strict["no"] == 4 and strict["yes"] == 0, strict   # silence read as "no"
    assert "non-committal" in verdict_line(strict), verdict_line(strict)
    assert len(strict["votes"]) == 4                          # still traceable
    assert looks_yesno("guys did the latest fedora 44 update cause your kernel to delete")
    assert looks_yesno("Anyone else losing grub after the update?")
    assert not looks_yesno("what changed in the fedora 44 update")
    # Both measured false positives, and both harmful: each went on to report a
    # head-count for a help request. A contraction is not an auxiliary...
    assert not looks_yesno("Can't set Firefox as default on Fedora 44 KDE")
    assert not looks_yesno("Can't quit Chrome on Mac")
    # ...and a subject in front of the verb makes it a statement.
    assert not looks_yesno("W32tm is making me lose my sleep")
    assert not looks_yesno("I have this sensor configured in my zigbee2mqtt setup")
    assert not looks_yesno("My laptop is repeatedly crashing whenever i play game")
    # A title that ends in a question mark and names no wh-word is a yes/no
    # question whatever its verb; the same fragment inside a body is not.
    assert looks_yesno("No more synced groups for snapcast clients?", is_title=True)
    assert not looks_yesno("Especially the Samsung ecosystem with it?")
    assert not looks_yesno("How to get Home Assistant more reliable?", is_title=True)
    assert stance("no issues here, works fine") == "no"
    assert stance("same here, had to reinstall") == "yes"
    print("ok —", verdict_line(t))


if __name__ == "__main__":
    _demo()
