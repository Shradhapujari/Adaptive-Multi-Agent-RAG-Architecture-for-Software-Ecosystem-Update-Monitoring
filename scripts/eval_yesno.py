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

    python3 scripts/eval_yesno.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yesno  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "yesno_questions_50" / "snapshot.json"

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


def load() -> list:
    snap = json.loads(SNAPSHOT.read_text())
    print(f"snapshot {snap['fetched_utc']}  sha256 {snap['sha256'][:12]}  n={snap['n']}")
    return snap["data"]


def detected(row: dict) -> bool:
    """The app flags on the user's question; here title and body both stand in."""
    return (yesno.looks_yesno(row.get("title", ""), is_title=True)
            or yesno.looks_yesno(row.get("author_description") or ""))


def main() -> int:
    rows = load()
    flagged = {i for i, r in enumerate(rows) if detected(r)}
    truth = set(IS_YESNO)

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

    answerable = [i for i in sorted(truth) if TRUE_VERDICT[i] is not None]
    print(f"\nVERDICT over the {len(truth)} genuine yes/no questions")
    decided = correct = 0
    for i in sorted(truth):
        t = yesno.tally(rows[i])
        call = ("yes" if t["yes"] > t["no"] else "no" if t["no"] > t["yes"]
                else "split") if t["answered"] else None
        want = TRUE_VERDICT[i]
        if call is not None:
            decided += 1
            correct += (call == want)
            mark = "ok " if call == want else "WRONG"
        else:
            mark = "abstain" if want is None else "MISS"
        print(f"  [{i:2d}] {mark:7s} system={str(call):5s} truth={str(want):5s}  {IS_YESNO[i][:44]}")

    print(f"\n  answerable from the comments   : {len(answerable)} of {len(truth)}"
          f"  (the rest have no answer in them, and abstaining is correct)")
    print(f"  reached a call                 : {decided} of {len(answerable)}")
    print(f"  call agreed with the labeller  : {correct} of {decided}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
