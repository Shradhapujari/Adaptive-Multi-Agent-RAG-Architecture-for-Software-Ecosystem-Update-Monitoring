"""A question answered as asked: "What bugs were fixed in Chrome recently?"

Live 2026-10-27 the console led with "🔴 Patch urgently" and llama3.1's whole
paragraph was ten bare CVE ids. The vendor's own release posts were never
fetched (no keyless web search ran), and nothing rejected a list that named no
bug. Offline throughout: the search is substituted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_agent  # noqa: E402
import app_1  # noqa: E402
import guardrail  # noqa: E402
import websearch  # noqa: E402


def test_websearch_self_check(monkeypatch):
    # _demo patches these in place; monkeypatch puts the real ones back after.
    monkeypatch.setattr(websearch, "_raw_search", websearch._raw_search)
    monkeypatch.setattr(websearch, "available", websearch.available)
    websearch._demo()


def test_a_bare_cve_id_is_not_a_finding():
    ev = [answer_agent.Evidence(label="A1", kind="advisory", title="CVE-2026-113344",
                                detail="Use after free in Performance in Google Chrome")]
    bare = "Chrome fixed one bug [A1].\n\n1. CVE-2026-113344 [A1]."
    assert [v.code for v in guardrail.check(bare, ev).violations] == ["bare_item"]
    named = "Chrome fixed one bug [A1].\n\n1. Use after free in Performance, CVE-2026-113344 [A1]."
    assert guardrail.check(named, ev).ok, guardrail.check(named, ev).violations


def test_vendor_pages_are_cited_as_vendor_pages():
    page = {"title": "Stable Channel Update for Desktop", "source": "web_trusted",
            "host": "chromereleases.googleblog.com", "date": "2026-10-20",
            "url": "https://chromereleases.googleblog.com/2026/10/x.html",
            "body": "Chrome 156 fixes 12 security bugs."}
    ev = answer_agent.collect_evidence({"web": [page]})
    assert [(e.kind, e.label) for e in ev] == [
        ("web", "Vendor page - chromereleases.googleblog.com, 2026-10-20")]
    assert ev[0].line("S1").count("[untrusted:community]") == 1   # page text is data
    assert answer_agent.by_source(ev) == {"Vendor pages": ev}


def test_details_list_each_cve_with_its_fix():
    adv = {"title": "chrome adv", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-113344",
           "is_cve": True, "product": "chrome", "version": "156.0.8078", "date": "20261020",
           "notes": "Use after free in Performance in Google Chrome prior to 156.0.8078.47"}
    rel = {"title": "Chrome 156", "product": "chrome", "version": "156.0.8078.47",
           "date": "20261021", "url": "https://chromereleases.googleblog.com/x", "notes": "Stable"}
    t = answer_agent.details(answer_agent.collect_evidence({"releases": [adv, rel]}))
    assert t["security"][0]["CVE"] == "CVE-2026-113344"
    assert t["security"][0]["Fixed in"] == "156.0.8078.47"
    assert t["security"][0]["Affects"] == "chrome 156.0.8078"
    assert [p["Release"] for p in t["patches"]] == ["chrome v156.0.8078.47"]


def test_a_what_question_is_answered_with_the_fact_not_the_verdict():
    assert app_1._ASKS_WHAT.match("What bugs were fixed in Chrome recently?")
    assert not app_1._ASKS_WHAT.match("Is it safe to update Firefox right now?")


def test_the_basic_answer_counts_names_and_says_which_version():
    def adv(cve, ver, note):
        return {"title": "x", "url": f"https://nvd.nist.gov/vuln/detail/{cve}", "is_cve": True,
                "product": "chrome", "version": ver, "date": "20261020", "notes": note}
    ev = answer_agent.collect_evidence({"releases": [
        adv("CVE-2026-1", "156.0.8078", "Use after free in Performance in Google Chrome prior to "
                                        "156.0.8078.47 allowed a remote attacker to run code."),
        adv("CVE-2026-2", "155.0.8059", "Confused deputy in Mobile in Google Chrome on iOS prior "
                                        "to 155.0.8059.39 allowed a bypass."),
        adv("CVE-2026-3", "2026.5.1", "OpenClaw versions before 2026.8.0 fail to apply approval."),
    ]})
    line = answer_agent.summary_line(ev)
    # All three counted; only the two that name Chrome name a flaw.
    assert line.startswith("Recent Chrome updates fixed 3 security bug(s), including "
                           "use after free in Performance and confused deputy in Mobile."), line
    assert line.endswith("Update to Chrome 156.0.8078.47 or later."), line   # not OpenClaw's 2026.8.0
    assert answer_agent.summary_line([]) == ""


def test_an_answer_cut_mid_sentence_is_truncated():
    ev = [answer_agent.Evidence(label="A1", kind="advisory", title="CVE-2026-91749",
                                detail="Use after free in Workers via a crafted HTML page")]
    cut = "Use after free in Workers [A1]. Use after free in Workers via a crafted HTML"
    assert [v.code for v in guardrail.check(cut, ev).violations] == ["truncated"]
    assert guardrail.check(cut + " page [A1].", ev).ok
