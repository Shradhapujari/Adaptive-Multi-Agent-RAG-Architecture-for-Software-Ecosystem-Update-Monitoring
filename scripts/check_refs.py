#!/usr/bin/env python3
"""Cross-reference sweep over the paper and its supplement.

Three defects have reached the repository from page-limit surgery: four \\cite
keys that existed in no .bib, a "items 6 and 8" pointer into a seven-item list,
and six "Table S6..S9" pointers at a supplement whose tables printed 1..4.
LaTeX reports none of them -- an undefined \\ref is loud, a *wrong* one is
silent. This checks the silent ones.

It also checks a second family, found by reading the typeset PDF end to end:
a setup or threats section that drifted from the results it describes. §3.11
claimed "All experiments were performed using Llama 3.1 8B" while §4.4 judged
with qwen2.5:7b-instruct, and §5.5 called 500 questions the largest evaluation
after §4.6.5 reported 1,000. Both are internally consistent and wrong only
against a section thirty pages away, which is exactly what a reader catches and
a build does not.

    python scripts/check_refs.py            # exit 1 if anything is wrong
    python scripts/check_refs.py --selfcheck
"""
import re, sys, collections, pathlib

PAPER = pathlib.Path(__file__).resolve().parent.parent / "paper"
NOUN = {"sec": {"section", "sections", "subsection"}, "tab": {"table", "tables"},
        "fig": {"figure", "figures"}, "eq": {"equation", "equations"},
        "alg": {"algorithm"}, "app": {"appendix"}}


def check(main_src, sup_src):
    """Return a list of complaints. Pure function of the two sources."""
    bad = []

    # 1. every \cite key resolves to a @entry in references.bib
    bib = (PAPER / "references.bib").read_text() if (PAPER / "references.bib").exists() else ""
    if bib:
        defined = set(re.findall(r"@\w+\{([^,]+),", bib))
        for src, name in ((main_src, "paper"), (sup_src, "supplement")):
            for group in re.findall(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]+)\}", src):
                for key in (k.strip() for k in group.split(",")):
                    if key and key not in defined:
                        bad.append(f"{name}: \\cite{{{key}}} is in no .bib entry")

    # 2. the noun in front of a \ref matches the label's type
    for src, name in ((main_src, "paper"), (sup_src, "supplement")):
        for m in re.finditer(r"(\w+)~\\(?:ref|autoref|Cref|cref)\{([^}]+)\}", src):
            noun, key = m.group(1).lower(), m.group(2)
            prefix = key.split(":")[0]
            if prefix in NOUN and noun in set().union(*NOUN.values()) and noun not in NOUN[prefix]:
                bad.append(f"{name}: '{m.group(1)}~\\ref{{{key}}}' -- label is a {prefix}")

    # 3. hand-written "Section/Table S<n>" pointers land on a real supplement part
    have = set()
    for a, b in re.findall(r"\\(?:sub)*section\*?\{(S[0-9]+(?:\.[0-9]+)?)(?:--S?([0-9]+))?", sup_src):
        have.add(a)
        if b:
            have.update(f"S{i}" for i in range(int(a[1:]), int(b) + 1))
    for tgt in set(re.findall(r"(?:Section|Table|Figure)~?(S[0-9]+(?:\.[0-9]+)?)", main_src)):
        if tgt not in have:
            bad.append(f"paper: points at {tgt}, which the supplement does not define")

    # 4. a "Table S<n>" pointer needs the supplement to *print* that number
    if re.search(r"Table~?S[0-9]", main_src) and r"\thetable" not in sup_src:
        bad.append("paper: cites 'Table S<n>' but the supplement does not renumber "
                   "its tables (they will print as 1, 2, 3...)")

    # 5. item~N pointers stay inside their list
    for name, src in (("paper", main_src), ("supplement", sup_src)):
        for lo, body in ((m.start(), m.group(1)) for m in
                         re.finditer(r"\\begin\{enumerate\}(.*?)\\end\{enumerate\}", src, re.S)):
            n = body.count(r"\item")
            for num in re.findall(r"items?~(\d+)(?:\s+and~(\d+))?", body):
                for v in (x for x in num if x):
                    if int(v) > n:
                        bad.append(f"{name}: 'item~{v}' in a list of {n} items")
    bad += check_drift(main_src)
    return bad


# The setup section promises the configuration; the threats section bounds it.
# Both have drifted once when a later run landed and nobody walked back.
# Generation and judging models only. The setup's claim is scoped to those, so
# the embedding reranker (nomic-embed-text) does not belong here: it lives in
# the method section and naming it below only produces a false positive.
MODEL = re.compile(r"llama\s*~?3\.1|mistral|qwen2\.5:7b-instruct|gpt-4o", re.I)
NQ = re.compile(r"(\d{1,3}(?:\{,\}|,)?\d{0,3})[\s~-]*(?:question|questions)", re.I)


def _section(src, label, stop=r"\\(?:sub)*section"):
    r"""The body of the section carrying \label{label}, up to the next heading."""
    m = re.search(r"\\label\{" + re.escape(label) + r"\}", src)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(stop, rest)
    return rest[:nxt.start()] if nxt else rest


def _counts(text):
    out = set()
    for raw in NQ.findall(text):
        try:
            out.add(int(raw.replace("{,}", "").replace(",", "")))
        except ValueError:
            pass
    return out


def check_drift(src):
    """Setup and threats must not contradict the results they describe."""
    bad = []
    setup = _section(src, "sec:setup")
    threats = _section(src, "sec:threats", stop=r"\\section\b")
    results = src[src.find(r"\label{sec:results}"):src.find(r"\label{sec:discussion}")]
    if not (setup and results):
        return bad

    # a model the results use that the setup never names
    named = {m.group(0).lower().replace("~", "").replace(" ", "") for m in MODEL.finditer(setup)}
    for m in MODEL.finditer(results):
        tok = m.group(0).lower().replace("~", "").replace(" ", "")
        if tok not in named:
            bad.append(f"paper: results use {m.group(0)!r}, which "
                       f"\\label{{sec:setup}} never names -- setup claims a configuration "
                       f"the results do not follow")
            break

    biggest_run = max(_counts(results), default=0)

    # a sample larger than anything the setup or threats admits to
    biggest_claimed = max(_counts(setup) | _counts(threats), default=0)
    if biggest_run > biggest_claimed:
        bad.append(f"paper: results report {biggest_run} questions; setup and threats "
                   f"top out at {biggest_claimed} -- one of them has not been walked "
                   f"forward")

    # a superlative in threats has to answer to the results, not to the setup.
    # Pooling the two sections hides exactly the defect that shipped: the setup
    # had been walked forward to 1,000 while threats still called 500 the
    # largest evaluation.
    sup = re.search(r"largest evaluation[^.;]*?(\d{1,3}(?:\{,\}|,)?\d{0,3})"
                    r"[\s~-]*(?:[A-Za-z-]+[\s~-]+){0,3}questions?", threats, re.I)
    if sup and biggest_run:
        claimed = int(sup.group(1).replace("{,}", "").replace(",", ""))
        if claimed != biggest_run:
            bad.append(f"paper: threats calls {claimed} questions the largest evaluation; "
                       f"the results report {biggest_run}")
    return bad


def selfcheck():
    ok = check(r"See Table~\ref{fig:x} and Section~S9." + "\n" + r"\cite{nosuchkey}",
               r"\section*{S1\quad A}")
    assert any("label is a fig" in c for c in ok), ok
    assert any("S9" in c for c in ok), ok
    assert any("nosuchkey" in c for c in ok), ok
    assert check(r"Figure~\ref{fig:x}", r"\section*{S1\quad A}") == [], "clean input must pass"

    # the two drift defects that actually shipped
    drifted = r"""\subsection{Setup}\label{sec:setup} All experiments used Llama~3.1 8B.
    The benchmark set is 500 questions.
    \section{Results}\label{sec:results} judged by qwen2.5:7b-instruct over 1{,}000 questions.
    \subsection{Threats}\label{sec:threats} The largest evaluation is 500 questions.
    \section{Discussion}\label{sec:discussion}"""
    out = check_drift(drifted)
    assert any("qwen" in c for c in out), out
    assert any("1000 questions" in c for c in out), out

    # the shape that actually shipped: setup walked forward, threats left behind
    half = drifted.replace("The benchmark set is 500 questions.",
                           "The benchmark set is 500 questions, extending to 1{,}000 questions.")
    out2 = check_drift(half)
    assert any("largest evaluation" in c for c in out2), out2
    walked = drifted.replace("All experiments used Llama~3.1 8B.",
                             "Llama~3.1 8B, except where qwen2.5:7b-instruct judges.") \
                    .replace("The largest evaluation is 500 questions.",
                             "The largest evaluation is 1{,}000 questions.")
    assert check_drift(walked) == [], check_drift(walked)
    print("selfcheck ok")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck(); sys.exit(0)
    problems = check((PAPER / "tosem_amara.tex").read_text(),
                     (PAPER / "supplementary.tex").read_text())
    for p in problems:
        print("FAIL", p)
    print(f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
