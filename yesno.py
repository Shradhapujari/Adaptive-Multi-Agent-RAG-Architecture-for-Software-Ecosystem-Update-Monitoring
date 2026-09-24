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

__all__ = ["looks_yesno", "asks_yesno", "stance", "tally", "verdict_line",
           "fetch_thread", "find_thread", "list_questions", "top_comment"]

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

# Three tiers, checked in this order, each measured on the three frozen sets
# that were in-sample by 2026-09-14 (scripts/eval_yesno.py):
#
#   1. A negated experience is a "no" and wins over everything: "never had
#      the same issue" contains "same issue", so the negations go first.
#   2. A shared experience is a "yes".
#   3. "works fine" / "runs fine" is a "no" only when nothing above matched:
#      measured on the fresh 50, both harmful head-counts came from these two
#      phrases inside comments that were not answering -- one of them opened
#      "it's not just you", which is a yes.
#
# The bare words -- yes / yeah / yep / no / nope -- count only as the first
# word of a top-level comment: an answer to the post. Anywhere else they are
# conversational ("yeah the mod's read is right", in a reply to that mod; a
# quoted "> ... Yes."), and measured wrong on three of the four calls the
# third 50 got wrong. Quoted lines (> ...) are dropped before matching:
# they are the other person's words.
NO_MARKERS = (
    "never had", "never heard", "never seen", "never experienced", "never happened",
    "never noticed", "no issue", "no issues", "no problem", "no problems", "not had",
    "haven't had", "havent had", "have not had", "not seen", "haven't seen",
    "hasn't happened", "didn't happen", "did not happen", "no such", "mine is fine",
    "all fine", "not for me", "not affected", "not having", "doesn't happen",
    "does not happen", "no trouble", "without any problem", "without any issue",
)
YES_MARKERS = (
    "same here", "same issue", "same problem", "same thing", "same boat",
    "similar issue", "similar problem", "something similar", "exact same",
    "me too", "me as well", "happened to me", "happened here", "happens to me",
    "happening to me",
    "i had this", "i have this", "i've had this", "i have had this", "having this too",
    "have this too", "can confirm", "confirmed", "affected me", "had to reinstall",
    "broke mine", "same for me", "not just you", "welcome to the club",
    "noticed this", "noticed the same", "also having", "also had", "also seeing",
    "also experienc", "did the same", "does the same", "doing the same",
    "started the same", "i'm seeing this", "im seeing this", "seeing the same",
    "run into this", "ran into this", "ran into the same", "run into the same",
)
WEAK_NO_MARKERS = ("works fine", "working fine", "runs fine", "running fine")
# "Yes, ..." / "Nope." -- the word, then punctuation. "No prosa, show code"
# and "No idea" open on the word too, and are not answers.
_OPENING_YES = re.compile(r"^\W*(?:yes|yeah|yep|yup|yess+)\s*[,.!;:—-]", re.I)
_OPENING_NO = re.compile(r"^\W*(?:no|nope|nah)\s*(?:[,.!;:—-]|$)", re.I)
_QUOTED_LINE = re.compile(r"^\s*(?:>|&gt;).*$", re.M)
# A yes-phrase with a negation in the three words before it is the negated
# experience, not the shared one: "haven't noticed this", "not seeing the
# same", "never ran into this". Tier 1 catches only the negations spelled out
# in NO_MARKERS, and every yes-phrase the rework added has a negated form
# that is not. Checked on the text before the match, so "it's not just you"
# -- where the "not" is inside the phrase -- is still a yes.
_NEGATED_BEFORE = re.compile(
    r"\b(?:not|no|never|nobody|no one|haven'?t|hasn'?t|hadn'?t|didn'?t|don'?t|"
    r"doesn'?t|isn'?t|aren'?t|wasn'?t|weren'?t|can'?t|couldn'?t|won'?t)"
    r"(?:\s+\w+){0,3}\s*$", re.I)

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


# A head-count question asked somewhere inside the body rather than as its
# opening or its title: "Has anyone else run into this?", "Is this normal?".
# Measured on the tuning set and the fresh 50 (both in-sample by now), this
# shape was 1 of 9 and then 8 of 13 of the genuine questions, so a detector
# that reads only the title and the first words of the body misses most of
# them. Scanning every "?"-sentence for an auxiliary opener was tried first
# and measured worse (precision 0.50 -> 0.40 on the tuning set): a help post
# nearly always has some "Is there a way to ...?" in it. So the sentence has
# to name other people *and* an experience -- "anyone ... seen", "someone ...
# same issue", "you ever ... encountered" -- or ask whether something is
# normal. "Can you point me ...?" names the reader and asks for help; it does
# not fire, because "you" only counts alongside ever/also/too.
_SENTENCE_Q = re.compile(r"[^.?!\n]*\?")
_WHO = re.compile(r"\b(?:any\s?(?:one|body)|some\s?(?:one|body)|you\s+(?:ever|also|too|guys|all))\b", re.I)
_EXPERIENCE = re.compile(r"\b(?:else|experienc\w*|encounter\w*|same|issues?|problems?|seen|see|had|"
                         r"having|happen\w*|too|notic\w*|run(?:ning)? into)\b", re.I)
_NORMAL = re.compile(r"\bis\b.*\bnormal\b", re.I)


def asks_yesno(title: str, body: str) -> Optional[str]:
    """The yes/no question a thread asks, or None: title, body opener, or a
    head-count sentence anywhere in the body. Returns the text that fired so
    a flag can be argued with at the sentence level."""
    if looks_yesno(title or "", is_title=True):
        return title
    if looks_yesno(body or ""):
        return (body or "").strip().split("\n", 1)[0]
    for sent in _SENTENCE_Q.findall(body or ""):
        sent = sent.strip()
        if not sent or _HAS_WH.search(sent):
            continue
        if _NORMAL.search(sent) or (_WHO.search(sent) and _EXPERIENCE.search(sent)):
            return sent
    return None


def stance(text: str, top_level: bool = True) -> str:
    """One comment's answer to the question: yes | no | unclear.

    `top_level` is whether the comment answers the post rather than another
    comment; a bare opening "yes"/"no" only counts when it does.
    """
    own = _QUOTED_LINE.sub("", text or "")
    t = " " + re.sub(r"\s+", " ", own.lower()).strip() + " "
    for m in NO_MARKERS:
        if m in t:
            return "no"
    for m in YES_MARKERS:
        i = t.find(m)
        if i >= 0:
            return "no" if _NEGATED_BEFORE.search(t[:i]) else "yes"
    if top_level and _OPENING_YES.match(own.strip()):
        return "yes"
    if top_level and _OPENING_NO.match(own.strip()):
        return "no"
    for m in WEAK_NO_MARKERS:
        if m in t:
            return "no"
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
        s = stance(c.get("body", ""),
                   top_level=str(c.get("parent_id", "t3_")).startswith("t3_"))
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


def list_questions(limit: int = 25, page: int = 1, timeout: int = 20) -> List[dict]:
    """One page of the lake's question feed, comments inline, for a picker."""
    import requests
    try:
        r = requests.get(QUESTIONS_API, params={"where": "either", "limit": limit,
                                                "page": page, "showCount": "true"},
                         timeout=timeout)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def questions_total(timeout: int = 20) -> int:
    """How many questions the feed holds, or 0 if it cannot be reached.

    `list_questions` throws the pagination block away and returns only the
    rows, which is all a page-at-a-time picker needs. Sampling the feed needs
    the size of the thing being sampled: measured 2026-09-24 the feed held
    3212 threads over 643 pages, and a picker that draws its "random" question
    from whichever page is on screen is not sampling the feed, it is shuffling
    25 rows of it.

    Asks for one row, reads the count beside it -- `showCount` is what makes
    the endpoint report the total at all.
    """
    import requests
    try:
        r = requests.get(QUESTIONS_API, params={"where": "either", "limit": 1,
                                                "page": 1, "showCount": "true"},
                         timeout=timeout)
        r.raise_for_status()
        return int(r.json().get("pagination", {}).get("total", 0) or 0)
    except Exception:
        return 0


def newest(rows: List[dict]) -> Optional[dict]:
    """The most recently posted of `rows`, by the feed's own timestamp.

    Sorted here rather than trusted from the feed. The endpoint does return
    newest-first today (checked over limits 100 and 200 on 2026-09-24), but
    "the latest question" reading correctly only while an undocumented sort
    holds is a promise made on someone else's behalf.
    """
    dated = [r for r in (rows or []) if r.get("created_utc")]
    if not dated:
        return (rows or [None])[0]
    return max(dated, key=lambda r: str(r.get("created_utc")))


def filter_questions(rows: List[dict], vendor_name: str = "") -> List[dict]:
    """Threads that are yes/no questions, optionally about one product.

    A thread is about `vendor_name` when its subreddit is that product's forum
    or the name appears in its title or body. Empty `vendor_name` keeps every
    yes/no thread.
    """
    import vendor
    v = (vendor_name or "").strip().lower()
    out = []
    for r in rows:
        title, body = r.get("title", ""), r.get("author_description", "")
        if not (looks_yesno(title, is_title=True) or looks_yesno(body)):
            continue
        if v and vendor.subreddit_vendor(r.get("subreddit", "")) != v \
                and v not in f"{title} {body}".lower():
            continue
        out.append(r)
    return out


def top_comment(thread: dict) -> Optional[dict]:
    """The one comment to present as the answer: highest Reddit score.

    Picking from many comments is done by the thread's own readers -- the
    score is their vote -- not by a second classifier here. Bots, removed
    comments and the asker's own follow-ups are excluded, since none of them
    is an answer. Ties go to the earlier comment (Reddit's own listing order).
    """
    asker = (thread.get("author") or "").lower()
    pool = [c for c in thread.get("comments") or []
            if (c.get("author") or "").strip().lower() not in _SKIP_AUTHORS
            and (c.get("author") or "").lower() != asker
            and not c.get("is_submitter") and (c.get("body") or "").strip()]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.get("score") or 0, -(c.get("created_utc_ts") or 0)))


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
    rows = [{"title": "Did the update delete grub?", "subreddit": "fedora"},
            {"title": "Anyone else on Debian losing wifi?", "subreddit": "linux"},
            {"title": "How do I fix grub", "subreddit": "fedora"}]
    assert [r["subreddit"] for r in filter_questions(rows)] == ["fedora", "linux"]
    assert len(filter_questions(rows, "fedora")) == 1       # by subreddit
    assert len(filter_questions(rows, "debian")) == 1       # by title
    assert filter_questions(rows, "chrome") == []
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
    tc = top_comment({"author": "op", "comments": [
        {"author": "AutoModerator", "body": "bot", "score": 99},
        {"author": "op", "body": "mine", "score": 50, "is_submitter": True},
        {"author": "a", "body": "low", "score": 1, "created_utc_ts": 1},
        {"author": "b", "body": "best", "score": 7, "created_utc_ts": 2},
        {"author": "c", "body": "tie-later", "score": 7, "created_utc_ts": 3},
    ]})
    assert tc["body"] == "best", tc                          # bot and OP skipped, tie -> earlier
    assert top_comment({"comments": []}) is None
    body = ("My light takes 30 seconds to respond since the update. I reinstalled "
            "the integration. Has anyone else run into this? Any ideas?")
    assert asks_yesno("Govee light slow after update", body).startswith("Has anyone else")
    assert asks_yesno("592 Updates", "I havent turned it on for a month, is the amount actually normal?")
    # A body that *opens* on an auxiliary is the pre-existing opener rule's
    # business; the mid-body rule is what has to stay quiet on these.
    assert asks_yesno("Discover broken", "Hey guys. Updates run fine in the shell. "
                      "Can you please point me in the right direction solving this issue?") is None
    assert asks_yesno("Haptics", "I upgraded to the F8 pro. Is this a feature or a bug? "
                      "Is there a way I can resolve this?") is None
    assert asks_yesno("Did the update delete grub?", "") == "Did the update delete grub?"
    assert stance("no issues here, works fine") == "no"
    assert stance("If that's 5.1.37, it's not just you. Mine is working fine now.") == "yes"
    assert stance("Yes, I have two similar models, one started the same thing as yours") == "yes"
    assert stance("yeah the mod's 'wait for the next stable' is the right read", top_level=False) == "unclear"
    assert stance("Yeah, mine did that after the update too.") == "yes"
    assert stance("&gt; does this mean I have to upgrade?\n\nIt's not mandatory.") == "unclear"
    assert stance("No, you don't have to rush.") == "no"
    assert stance("No idea, but try TrixLoader.") == "unclear"
    assert stance("No prosa, show code") == "unclear"
    assert stance("Nope") == "no"
    assert stance("this has been happening to me on one of my 4 UNVRs") == "yes"
    assert stance("My phone recently did something similar, let the battery die.") == "yes"
    assert stance("same here, had to reinstall") == "yes"
    # A negation ahead of a yes-phrase is the negated experience. These four
    # all returned "yes" before the look-back; none of them is a head-count.
    assert stance("I haven't noticed this at all") == "no"
    assert stance("Not seeing the same on my end") == "no"
    assert stance("Haven't run into this yet") == "no"
    assert stance("never ran into this") == "no"
    assert stance("I did not have the same issue") == "no"
    # ...and the negation that is part of the phrase, or before a comma, is not.
    assert stance("If that's 5.1.37, it's not just you.") == "yes"
    assert stance("No, same here.") == "yes"
    print("ok —", verdict_line(t))


if __name__ == "__main__":
    _demo()
