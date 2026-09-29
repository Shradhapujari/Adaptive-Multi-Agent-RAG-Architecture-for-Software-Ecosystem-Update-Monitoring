#!/usr/bin/env python3
"""Cross-reference sweep over the paper and its supplement.

Three defects have reached the repository from page-limit surgery: four \\cite
keys that existed in no .bib, a "items 6 and 8" pointer into a seven-item list,
and six "Table S6..S9" pointers at a supplement whose tables printed 1..4.
LaTeX reports none of them -- an undefined \\ref is loud, a *wrong* one is
silent. This checks the silent ones.

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
    return bad


def selfcheck():
    ok = check(r"See Table~\ref{fig:x} and Section~S9." + "\n" + r"\cite{nosuchkey}",
               r"\section*{S1\quad A}")
    assert any("label is a fig" in c for c in ok), ok
    assert any("S9" in c for c in ok), ok
    assert any("nosuchkey" in c for c in ok), ok
    assert check(r"Figure~\ref{fig:x}", r"\section*{S1\quad A}") == [], "clean input must pass"
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
