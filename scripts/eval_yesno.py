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

    python3 scripts/eval_yesno.py --set third   # blind set for the mid-body rule

The mid-body rule (`yesno.asks_yesno`) was written against the first two
sets, then the third 50 (frozen 2026-09-14, sha256 27d32141, no thread in
common with either) was labelled and run once. Its figures are the only
out-of-sample ones for that rule -- and it is in-sample for anything after.

    python3 scripts/eval_yesno.py --set fourth  # blind set for the stance-marker rework

The stance markers were reworked against the first three sets (tiers,
opening-word-only yes/no on top-level comments, quoted lines dropped) and
the fourth 50 (frozen 2026-09-14, sha256 9f96ed95) was labelled from full
bodies and run once. Every set is in-sample now; the next change needs a
fifth.
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
    # Added 2026-09-14 under the criterion the fresh 50 was labelled with: a
    # post that asks whether others share the experience is a yes/no question
    # even when the rest of it is a help request -- the head-count answers
    # that ask, and the UI shows it above the answer, not instead of it. The
    # 2026-09-09 labels read these four as help requests; the figures quoted
    # for that labelling (precision 0.80, recall 0.89, 6 of 7, 6 of 6) are
    # against the nine above only.
    11: "anyone with this problem",                                   # mid-body
    22: "has anyone else run into this",                              # mid-body
    33: "has anyone else seen comparable instability after updates",  # mid-body
    39: "does anyone encounter an issue like this",                   # mid-body; 0 comments
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
    11: None,   # three comments explain activation lock; nobody reports it
    22: "yes",  # "mine did the same thing a while back"
    33: "yes",  # four "same issue"/"happening to me", three "no problems" -- close
    39: None,   # no comments at all
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

# ---- Third 50: the blind set for the mid-body rule ------------------------
# Pages 2-3 on 2026-09-14, frozen (sha256 27d32141) before the rule existed,
# labelled 2026-09-14 by reading every body and every comment on the genuine
# threads *before* the rule was run on it. Same criterion as the two sets
# above after their 2026-09-14 unification. Comment-poor: five of the
# sixteen genuine threads have no comments at all.
#
# Result, one run, then frozen (2026-09-14):
#   title+opener rule only : precision 0.60  recall 0.38  harmful head-counts 2
#   with the mid-body rule : precision 0.71  recall 0.62  harmful head-counts 2
# The four threads the mid-body rule added (27, 29, 38, 41) are all genuine;
# both harmful calls come from the older title rule (0 "Anyone know how",
# 49 "Linux or Windows? Thoughts?"). The six misses are questions the rule
# does not target -- factual yes/no with no "anyone" in them (21, 25, 31,
# 40), a title that ends in "." after its "?" (4), and a poll sentence that
# also contains "how" (18). Verdicts stay the weak half: 4 calls on the 5
# answerable, 2 right; "yeah" and a quoted "Yes," inside explanations.
IS_YESNO_THIRD = {
    1:  "is Face ID really secure / has anyone else experienced this",   # title + mid-body
    4:  "does anyone else experience this Edge censorship",             # title ("dose")
    8:  "does Apple budge on not installing the latest OS",             # title
    13: "are the 2026.8.2 BTHome integrations broken",                  # title, 0 comments
    20: "has the AX211 6 GHz problem ever been solved",                  # title, 0 comments
    21: "is Chrome now treated as essential",                           # body opener, 0 comments
    25: "have you found a reliable way to update without breaking",     # mid-body poll
    31: "does 11's EOL mean I have to upgrade in the next few days",    # mid-body, factual
    38: "has anyone seen AADSTS500032 in an Azure VM login before",     # mid-body
    40: "will I get back into iCloud on a new phone",                   # mid-body, factual
    41: "has anyone seen AADSTS500032 in an Azure VM login before",     # mid-body (cross-post of 38)
    43: "anyone having issues downloading the update on 5G",            # title
    44: "anyone having issues downloading the update on 5G",            # title (cross-post of 43)
    # Added after the first run, and said so: the blind pass read bodies cut
    # at 1,100 characters, and these three ask their question past that. The
    # rule had flagged 27 and 29 (counted as false positives on that run) and
    # had NOT flagged 18 (its sentence also contains "how"), so the correction
    # moves one number each way. Full bodies were re-read for the whole set;
    # nothing else past the cut is a yes/no ask (2 "anyone has an idea", 37
    # "does anyone know what", 48 "can anyone help").
    18: "has anyone else had this issue recently",                       # mid-body, past 1,100 chars
    27: "is this behavior anyone has seen",                              # mid-body, past 1,100 chars
    29: "has anyone experienced something similar",                      # mid-body, past 1,100 chars
}
# Read as not yes/no, for the record: 0 "anyone know how" (how); 3, 17, 42
# "is there a way" (how-to); 5, 39 "does anyone know what/if ... or" (wh,
# A-or-B); 28, 49 A-or-B; 32 "should i reinstall" trails a crash rant with
# no question mark -- the closest call in the set.

TRUE_VERDICT_THIRD = {
    1:  None,   # no comments
    4:  None,   # no comments
    8:  "no",   # "No they don't", "making a fuss wont get you anywhere", the repair terms quoted
    13: None,   # no comments
    20: None,   # no comments
    21: None,   # no comments
    25: None,   # fifteen comments of strategy (backup, replica, wait for stable); no head-count in them
    31: "no",   # "It's not mandatory", "No, you don't have to rush", "still possible after support ends"
    38: None,   # "I don't have an answer"; the rest are questions back
    40: None,   # nobody addresses the new-phone question
    41: None,   # questions back at the asker; nobody has seen it
    43: None,   # a settings tip and a note that iCloud was down
    44: None,   # "reddit reports say need to be on wifi" -- second-hand, not a report
    18: "yes",  # "i have the exact same issue on my macbook air m4"; a second "me too" in Chinese
    27: "yes",  # "Yes, I have two similar models ... one started the same thing as yours"
    29: "yes",  # "My phone recently did something similar" -- no marker phrase, so the tally abstains
}

# ---- Fourth 50: the blind set for the stance-marker change ----------------
# Pages 3-4 on 2026-09-14, frozen (sha256 9f96ed95) after the mid-body rule
# and before the marker rework; labelled from *full* bodies (the third set's
# lesson) and every comment, before either rule was run on it. Same
# criterion as the other three. Close calls, decided and recorded: 19
# ("Could it be that?" -- seeks a cause, not a head-count: no), 22 ("would
# this work, or would it stay locked" -- the "or" is the negation, so yes),
# 49 ("if it's gonna let me reset or not?" -- yes), 29 ("No cellular after
# update?" title over a troubleshooting body -- no).
#
# Result, one run, then frozen (2026-09-14):
#   detection, title+opener only : precision 0.88  recall 0.41  harmful 0
#   detection, with mid-body     : precision 0.92  recall 0.71  harmful 0
#     (a second blind figure for the mid-body rule; the five misses are the
#      two polls with no "?" (0, 13), two factual asks (2, 22) and 49's
#      "... or not?")
#   verdicts, old markers        : 10 answerable, 5 called, 2 right
#   verdicts, reworked markers   : 10 answerable, 5 called, 2 right -- identical
# The marker rework removed the third set's four wrong calls and changed
# nothing here. The three wrong calls are three different failures, none of
# them the ones the rework targeted: 24 "haven't had" inside a same-
# experience report; 49 "no problem" meaning "easily"; 34 "Yes, I have been
# seeing this" -- a true yes to "anyone else?" counted against "is this
# normal?", where shared experience is not the same answer.
IS_YESNO_FOURTH = {
    0:  "is it just me or is anyone else noticing this",               # mid-body, no "?"
    2:  "has there been a recent update that could be causing this",  # mid-body, factual
    5:  "is it a glitch in 26.6.1 / anyone else having this issue",    # mid-body
    9:  "is it okay to stop updating the phone",                       # title + body
    12: "someone had a similar issue and resolved it",                 # mid-body
    13: "I don't know if anyone else has this issue",                  # mid-body, no "?"
    14: "am I screwed",                                                # title
    17: "anyone else noticed this",                                    # mid-body
    22: "would removing the iPad from his account let it be reset",    # mid-body, factual
    24: "anyone else see a drastic change in DSv4Flash",               # mid-body
    34: "sleep mode broken / is this normal",                          # title + mid-body
    35: "does somebody have a solution or a similar problem",          # mid-body
    37: "is anyone else experiencing this right now",                  # mid-body
    40: "cameras disconnecting / anyone else",                         # title + mid-body
    42: "will the official API be updated to support 26.07",           # title, factual
    47: "anyone else notice their BCD files were updated",             # body opener
    49: "is it going to let me factory reset or not",                  # mid-body, no "?" before "or not?"
}

TRUE_VERDICT_FOURTH = {
    0:  None,   # VoLTE advice; nobody reports the same
    2:  None,   # a how-to-measure answer; the update question is not addressed
    5:  None,   # one suggestion (attention awareness)
    9:  "no",   # "Always keep updating"; the 13 GB is install headroom, not storage
    12: None,   # "the only flicker I know about is VRR" -- not a report
    13: "no",   # "It works for me" twice
    14: "no",   # OpenCore patcher; "your Mac DOES meet the requirements for Monterey"
    17: "yes",  # "I have Fold 8 too and same thing"
    22: "no",   # "Without the passcode, you're probably out of luck"
    24: "yes",  # two commenters describe the same runaway sessions
    34: "no",   # "Firstly, it's not normal", "Known bug" -- though six others say they have it too,
                # which is a yes to a question the asker did not ask; the tally will read them
    35: None,   # no comments
    37: "yes",  # "exactly the same problem" x5, "Same here"
    40: None,   # no comments
    42: None,   # "The official API is here. What you're using was never supported" -- the premise fails
    47: "yes",  # "Funny you say that I noticed that in threatlocker"
    49: "yes",  # "You'll be able to erase the iPad no problem"
}

SETS = {
    "original": (DATA / "yesno_questions_50" / "snapshot.json", IS_YESNO, TRUE_VERDICT),
    "fresh":    (DATA / "yesno_questions_50_fresh" / "snapshot.json", IS_YESNO_FRESH, TRUE_VERDICT_FRESH),
    "third":    (DATA / "yesno_questions_50_third" / "snapshot.json", IS_YESNO_THIRD, TRUE_VERDICT_THIRD),
    "fourth":   (DATA / "yesno_questions_50_fourth" / "snapshot.json", IS_YESNO_FOURTH, TRUE_VERDICT_FOURTH),
}


def load(snapshot: Path) -> list:
    snap = json.loads(snapshot.read_text())
    print(f"snapshot {snap['fetched_utc']}  sha256 {snap['sha256'][:12]}  n={snap['n']}")
    return snap["data"]


def detected(row: dict) -> bool:
    """What the app checks on a picked thread: title, body opener, mid-body."""
    return yesno.asks_yesno(row.get("title", ""), row.get("author_description") or "") is not None


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
    decided = decided_answerable = correct = 0
    for i in sorted(truth):
        t = yesno.tally(rows[i])
        call = ("yes" if t["yes"] > t["no"] else "no" if t["no"] > t["yes"]
                else "split") if t["answered"] else None
        want = true_verdict[i]
        if call is not None:
            decided += 1
            decided_answerable += (want is not None)
            correct += (call == want)
            mark = "ok " if call == want else "WRONG"
        else:
            mark = "abstain" if want is None else "MISS"
        print(f"  [{i:2d}] {mark:7s} system={str(call):5s} truth={str(want):5s}  {is_yesno[i][:44]}")

    spurious = decided - decided_answerable
    print(f"\n  answerable from the comments   : {len(answerable)} of {len(truth)}"
          f"  (the rest have no answer in them, and abstaining is correct)")
    print(f"  reached a call                 : {decided_answerable} of {len(answerable)}")
    print(f"  call agreed with the labeller  : {correct} of {decided_answerable}")
    if spurious:
        print(f"  called where nothing answers   : {spurious}  (a head-count off comments that do not answer)")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="original")
    raise SystemExit(main(ap.parse_args().set))
