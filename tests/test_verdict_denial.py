"""Prose under a red verdict may not deny it. Live, 2026-11-12: "Any critical
Linux kernel vulnerabilities right now?" showed 🔴 Patch urgently on 9
advisories with "Answer: There are no critical Linux kernel vulnerabilities
right now." directly beneath it (llama3.1)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_agent
from answer_agent import PresentedAnswer, drop_verdict_denials

PATCH = {"verdict": "patch_urgently", "rationale": "9 advisory document(s) name this product"}


def test_patch_now_drops_a_sentence_denying_vulnerabilities():
    body = ("There are no critical Linux kernel vulnerabilities right now. "
            "Kernel 6.17.3 ships the fixes.")
    assert drop_verdict_denials(body, "patch_urgently") == "Kernel 6.17.3 ships the fixes."


def test_patch_now_drops_safe_to_update_but_keeps_not_safe():
    assert drop_verdict_denials("It is safe to update Firefox right now.", "patch_urgently") == ""
    kept = "It is not safe to update Firefox until 159.0.2."
    assert drop_verdict_denials(kept, "patch_urgently") == kept


def test_list_items_are_never_dropped():
    body = "Findings:\n1. CVE-2026-10001 does not affect linux 6.1 [A1]"
    assert drop_verdict_denials(body, "patch_urgently") == body


def test_hold_keeps_no_vulnerabilities_but_drops_safe_to_update():
    # A hold is about regressions; "no known vulnerabilities" can be true under it.
    assert drop_verdict_denials("There are no known vulnerabilities.", "hold") \
        == "There are no known vulnerabilities."
    assert drop_verdict_denials("It is safe to update.", "hold") == ""


def test_other_verdicts_are_untouched():
    for v in ("safe", "update_with_caveat", "insufficient_evidence", None):
        assert drop_verdict_denials("It is safe to update.", v) == "It is safe to update."


def test_present_answer_strips_the_denial_after_the_lead(monkeypatch):
    monkeypatch.setattr(answer_agent, "unresolved_products", lambda q, r: [])
    monkeypatch.setattr(answer_agent, "_present", lambda *a, **k: PresentedAnswer(
        "There are no critical Linux kernel vulnerabilities right now.", "llm"))
    out = answer_agent.present_answer("q", {"decision": PATCH})
    lead = answer_agent.verdict_lead(PATCH)
    assert out.text == lead
    assert "contradicting the verdict" in out.note


def test_a_list_under_a_dropped_sentence_stays_a_list(monkeypatch):
    monkeypatch.setattr(answer_agent, "unresolved_products", lambda q, r: [])
    lead = answer_agent.verdict_lead(PATCH)
    monkeypatch.setattr(answer_agent, "_present", lambda *a, **k: PresentedAnswer(
        f"{lead} There are no critical vulnerabilities.\n\n1. CVE-2026-10001 [A1]", "llm"))
    out = answer_agent.present_answer("q", {"decision": PATCH})
    assert out.text == f"{lead}\n\n1. CVE-2026-10001 [A1]"


def test_patch_now_headline_is_composed_from_the_advisories(monkeypatch):
    # The model's hedge, live on 2026-11-12, became the console's answer line.
    import app_1
    adv = {"title": "linux adv", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-98934",
           "is_cve": True, "product": "linux", "version": "6.16.0", "date": "20261023",
           "notes": "In the Linux kernel, ipv6: sr: use skb_get_hash_net()"}
    ev = answer_agent.collect_evidence({"releases": [adv]})
    lead = answer_agent.verdict_lead(PATCH)
    hedge = "Note: The sources do not indicate that these vulnerabilities are critical or unpatched."
    shown = []
    for fn in ("markdown", "write", "caption"):
        monkeypatch.setattr(app_1.st, fn, lambda s, *a, **k: shown.append(str(s)))
    app_1._tab_short({"decision": PATCH, "releases": [],
                      "original_query": "Any critical Linux kernel vulnerabilities right now?"},
                     PresentedAnswer(f"{lead} {hedge}", "llm", evidence=ev))
    answer = shown[2:]  # Q, headline, then the one-line answer
    assert answer and "Recent Linux updates fixed 1 security bug(s)" in answer[0], shown
    assert not any("unpatched" in s for s in shown)


def test_summary_names_the_product_when_a_kev_row_sorts_first():
    # KEV rows carry no "affects" string; one sorting first gave "Recent Recent updates".
    kev = {"title": "[CISA KEV] Linux Kernel flaw", "source": "cisa_kev", "date": "20261028",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-46300",
           "detail": "Linux Kernel contains a missing initialization of a variable"}
    adv = {"title": "linux adv", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-98934",
           "is_cve": True, "product": "linux", "version": "6.16.0", "date": "20261023",
           "notes": "In the Linux kernel, ipv6: sr: use skb_get_hash_net()"}
    line = answer_agent.summary_line(answer_agent.collect_evidence({"releases": [adv], "cve": [kev]}))
    assert line.startswith("Recent Linux updates fixed 2 security bug(s)"), line
    only_kev = answer_agent.summary_line(answer_agent.collect_evidence({"cve": [kev]}))
    assert only_kev.startswith("Recent updates fixed 1 security bug(s)"), only_kev


def test_patch_now_drops_unconditional_advice_against_updating():
    # Live, llama3.1, 2026-11-20: under "Patch now", over a list whose first
    # item says Firefox 160.0.0 fixes the CVEs.
    body = ("It is not safe to update Firefox.\n\n"
            "1. Firefox 160.0.0 fixes CVE-2026-130020 [A1].\n\n"
            "Note: the advisories make it not safe to update.")
    # Leading newlines are kept on purpose: they separate the list from the lead.
    assert drop_verdict_denials(body, "patch_urgently") == \
        "\n\n1. Firefox 160.0.0 fixes CVE-2026-130020 [A1]."
    for s in ("Do not update Firefox yet.", "Avoid upgrading for now.",
              "It is unsafe to install this update."):
        assert drop_verdict_denials(s, "patch_urgently") == "", s


def test_patch_now_keeps_conditional_advice_and_hold_keeps_it_all():
    for s in ("Do not update until 160.0.1 ships.",
              "Wait to install it until the vendor posts the fix."):
        assert drop_verdict_denials(s, "patch_urgently") == s
    # Under "hold", advice against updating agrees with the verdict.
    assert drop_verdict_denials("It is not safe to update Firefox.", "hold") \
        == "It is not safe to update Firefox."
