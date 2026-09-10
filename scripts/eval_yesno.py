"""
Coverage and accuracy of the yes/no consensus, over a frozen 50-question feed.

Two questions, measured separately, because they fail in different ways:

  1. Detection -- of the questions in the feed, which does `looks_yesno` flag?
     A false positive here is a troubleshooting post about to be answered with
     a head-count.
  2. Verdict   -- of the questions that really are yes/no, on how many does the
     tally reach a call, and is the call right?

Ground truth is hand-labelled and lives in this file, next to the numbers it
produces, so a reader can disagree with a specific label rather than with the
result. It was assigned by reading each post's full body (not its title: six
of the fifty read as questions in the title and as help requests in the body)
and, for the verdicts, every comment on the nine genuine yes/no threads.

The labeller was the same agent that wrote the classifier, which is the
weakness of this measurement and the reason each label is quoted below rather
than asserted. n=9 is a count, not a rate: no confidence interval here would
mean anything, and none is reported.

The feed is frozen to data/yesno_questions_50/snapshot.json. It is live and
reorders daily; re-fetching would silently measure a different set.

Both fixes to `looks_yesno` were derived from that first 50, so its figures
are in-sample. `--set fresh` runs the identical procedure over a second,
non-overlapping 50 (page 2 of the same feed, frozen 2026-09-10, labelled
after the classifier was frozen): the out-of-sample number.

    python3 scripts/eval_yesno.py            # the original 50 (in-sample)
    python3 scripts/eval_yesno.py --set fresh
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yesno  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"

# Index -> why this post is a genuine yes/no question. Anything not listed was
# labelled "not yes/no": overwhelmingly help requests ("how do I fix this"),
# error dumps, and PSAs.
IS_YESNO = {
    5:  "did the update delete your kernel and grub",
    6:  "does anyone use HA-NFL anymore",
    7:  "is there a cache bug in the Claude Code CLI",
    9:  "anyone having this issue with frigate notifications",
    13: "could an external SSD save it",
    14: "anyone else having trouble keeping up",
    16: "did the update remove synced snapcast groups",
    34: "can Chrome updates be scheduled for weekends",
    48: "is this number of updates normal",
}

# What the thread's comments actually answer, read by hand. None = the
# comments do not answer it, so abstaining is the correct behaviour.
TRUE_VERDICT = {
    5:  "no",   # two commenters have never seen it; nobody confirms
    6:  "no",   # nobody reports using it; one has moved to ha-teamtracker
    7:  None,   # the one comment is itself a question, not an answer
    9:  "yes",  # "I've been having the exact same problem"
    13: None,   # no comments at all
    14: "yes",  # "I am kind of in the same boat", among many agreeing
    16: "yes",  # "they broke it in the update, same thing happened here"
    34: "yes",  # several describe doing exactly this via Chrome policy
    48: "yes",  # two flat "Yes." answers explaining why
}


# ---- Second, non-overlapping 50 ------------------------------------------
# Page 2 of the same feed, frozen 2026-09-10 after both classifier fixes had
# landed, so nothing below was seen while the rules were being written. Same
# protocol: full body read for every post; every comment read on the genuine
# yes/no threads. The 13 genuine questions split into two shapes, and the
# split is the finding: 5 carry the question in the title, 8 ask it mid-body
# ("Has anyone else encountered this ...") under a declarative title. That
# second shape was one post in the first 50 ("592 Updates") and is the
# majority here.
IS_YESNO_FRESH = {
    0:  "anyone seeing TRIM issues on Proxmox after the May Windows update",
    2:  "are the duplicate docker images safe to delete",
    12: "anyone else had the KDE desktop go unresponsive after sleep",   # mid-body
    18: "is anyone else seeing Chrome run hot after the update",         # mid-body
    19: "are Intune check-in and registration broken on Linux",
    21: "has this happened to anyone else on iOS 26",                    # title is A-or-B; the head-count ask is mid-body
    25: "anyone else have the mask-editor lag in Firefox",               # mid-body, under a "What happened" title
    27: "is someone else having the invalid-licence issue",              # mid-body
    28: "is 42-45 C idle normal after the update",                       # mid-body
    35: "have you encountered no sites loading after the Chrome update",  # mid-body
    36: "has anyone experienced the iPad losing internet on 17.7.11",     # mid-body
    39: "anyone uploading HDR photos with WordPress 7.1",
    45: "has anyone else had Remote Home-Assistant fail since the update",  # mid-body
}
# Not genuine, and flagged anyway (the false positives), for the record:
#   3  "Dell Micro 3080 and Unifi 5 OS?"  -- a noun phrase with a "?", no ask.
#      Tallied anyway as "No (1 users)": "working fine" fired inside a comment
#      that opens "it's not just you". The one vote points the wrong way.
#   5  "... the chances i might get hired ?"  -- a degree, not a yes/no; off-topic
#  22  "... Suggestions for troubleshooting?"  -- an open request
#  44  "... driver issue?"  -- body is a help request (akmod build failed)
#  49  "... one works and the other doesn't?"  -- a why-question; body asks for a setting

TRUE_VERDICT_FRESH = {
    0:  "yes",  # "I had a similar issue on a Windows 2019 server"; a workaround link
    2:  "yes",  # "unreferenced and safe to remove"; "old versions that lost their tag"
    12: "yes",  # named as two bugs in xwaylandvideobridge with a fix version
    18: None,   # two troubleshooting suggestions, nobody reports the same
    19: "yes",  # "Can confirm", "Same here", "Same issue on our end", "We have noticed this"
    21: None,   # one comment answers the A-or-B (hardware); nobody says it happened to them
    25: None,   # "No clue", then a plugin recommendation
    27: "yes",  # "welcome to the club"; Netgate staff confirm the promotion ended.
                # The tally also says yes -- but off a sarcastic "Yes. How dare
                # we." from the staff reply, not off "welcome to the club". Right
                # for the wrong reason; counted as a hit below, flagged here.
    28: "no",   # power it down; "probably something running in the background"
    35: None,   # "I don't have that behavior but the equivalent" -- neither
    36: None,   # both comments are questions back at the asker
    39: None,   # two comments about 7.1's features; nobody says they are
    45: None,   # no comments at all
}

SETS = {
    "original": (DATA / "yesno_questions_50" / "snapshot.json", IS_YESNO, TRUE_VERDICT),
    "fresh":    (DATA / "yesno_questions_50_fresh" / "snapshot.json", IS_YESNO_FRESH, TRUE_VERDICT_FRESH),
}


def load(snapshot: Path) -> list:
    snap = json.loads(snapshot.read_text())
    print(f"snapshot {snap['fetched_utc']}  sha256 {snap['sha256'][:12]}  n={snap['n']}")
    return snap["data"]


def detected(row: dict) -> bool:
    """The app flags on the user's question; here title and body both stand in."""
    return (yesno.looks_yesno(row.get("title", ""), is_title=True)
            or yesno.looks_yesno(row.get("author_description") or ""))


def main(which: str = "original") -> int:
    snapshot, is_yesno, true_verdict = SETS[which]
    rows = load(snapshot)
    flagged = {i for i, r in enumerate(rows) if detected(r)}
    truth = set(is_yesno)

    tp, fp, fn = flagged & truth, flagged - truth, truth - flagged
    print(f"\nDETECTION over {len(rows)} questions")
    print(f"  genuine yes/no (hand-labelled) : {len(truth)}")
    print(f"  flagged by looks_yesno         : {len(flagged)}")
    print(f"  true positives {len(tp):2d}  false positives {len(fp):2d}  missed {len(fn):2d}")
    print(f"  precision {len(tp)/max(len(flagged),1):.2f}   recall {len(tp)/max(len(truth),1):.2f}")

    print("\n  false positives — what the tally then does with them:")
    for i in sorted(fp):
        t = yesno.tally(rows[i])
        verdict = yesno.verdict_line(t)
        harm = "ABSTAINS" if not t["answered"] else "ANSWERS ANYWAY"
        print(f"    [{i:2d}] {harm:14s} {rows[i]['title'][:44]:44s} {verdict[:38]}")
    print("  missed:")
    for i in sorted(fn):
        print(f"    [{i:2d}] {rows[i]['title'][:60]}")

    answerable = [i for i in sorted(truth) if true_verdict[i] is not None]
    print(f"\nVERDICT over the {len(truth)} genuine yes/no questions")
    decided = correct = 0
    for i in sorted(truth):
        t = yesno.tally(rows[i])
        call = ("yes" if t["yes"] > t["no"] else "no" if t["no"] > t["yes"]
                else "split") if t["answered"] else None
        want = true_verdict[i]
        if call is not None:
            decided += 1
            correct += (call == want)
            mark = "ok " if call == want else "WRONG"
        else:
            mark = "abstain" if want is None else "MISS"
        print(f"  [{i:2d}] {mark:7s} system={str(call):5s} truth={str(want):5s}  {is_yesno[i][:44]}")

    print(f"\n  answerable from the comments   : {len(answerable)} of {len(truth)}"
          f"  (the rest have no answer in them, and abstaining is correct)")
    print(f"  reached a call                 : {decided} of {len(answerable)}")
    print(f"  call agreed with the labeller  : {correct} of {decided}")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="original")
    raise SystemExit(main(ap.parse_args().set))
