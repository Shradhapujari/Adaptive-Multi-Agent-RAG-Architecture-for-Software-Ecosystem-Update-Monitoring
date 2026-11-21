"""Head-to-head: our verdict against competitors on one labelled decision sheet.

    python scripts/head_to_head.py data/decision_benchmark_200.jsonl

Gold is the verdict both annotators gave; rows they disagree on, or left
empty, have no gold and are skipped (and counted). Every system answers each
gold row with one label -- act / hold / insufficient_evidence -- or None when
its reply carried no clean label. The lead number is the false-green rate:
of the questions whose answer is "hold", the share a system said "act" on.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from ask_external_models import load_dotenv  # noqa: E402
from decide import COLLAPSE, decide  # noqa: E402
from eval_harness.providers import LLMError, make_client  # noqa: E402

LABELS = ("act", "hold", "insufficient_evidence")
ERROR = "error"   # the call failed (rate limit, truncation): not the model's fault
_VERDICT = re.compile(r"^\s*verdict:(.*)$", re.IGNORECASE | re.MULTILINE)
_LABEL = re.compile(r"\b(act|hold|insufficient_evidence)\b", re.IGNORECASE)
_MARKDOWN = re.compile(r"[*#>`]|(?<!\w)_|_(?!\w)")  # keeps insufficient_evidence intact


def load_gold(path: str) -> list[dict]:
    """Rows both annotators labelled the same way, each with a `gold` key."""
    rows = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            v1 = (r.get("a1") or {}).get("verdict")
            v2 = (r.get("a2") or {}).get("verdict")
            if v1 and v1 == v2:
                rows.append(r | {"gold": v1})
    return rows


def parse_verdict(text: str) -> str | None:
    """The label on the last `VERDICT:` line. None if there is none, or if that
    line names more than one label ("act or hold" is a hedge, not an answer)."""
    lines = _VERDICT.findall(_MARKDOWN.sub("", text or ""))
    if not lines:
        return None
    labels = {m.lower() for m in _LABEL.findall(lines[-1])}
    return labels.pop() if len(labels) == 1 else None


def score(gold: list[str], pred: list[str | None]) -> dict:
    """accuracy counts every row (no answer = wrong); accuracy_answered and
    false_green count only rows the system gave a label on."""
    n = len(gold)
    answered = [(g, p) for g, p in zip(gold, pred) if p in LABELS]
    holds = [p for g, p in answered if g == "hold"]
    return {
        "n": n,
        "accuracy": sum(g == p for g, p in zip(gold, pred)) / n if n else None,
        "accuracy_answered": sum(g == p for g, p in answered) / len(answered) if answered else None,
        "errors": sum(p == ERROR for p in pred),
        "n_hold": len(holds),
        "false_green": sum(p == "act" for p in holds) / len(holds) if holds else None,
        "abstain": sum(p == "insufficient_evidence" for p in pred) / n if n else None,
        "unparsed": sum(p is None for p in pred),
    }


# --- systems: each is (row) -> label | None ---------------------------------

PROMPT = """You are deciding whether someone should update software.

Question: {query}
{context}{evidence}
Answer with your reasoning, then a final line that is exactly one of:
VERDICT: act                    (the evidence supports doing something now: install, stay, apply a fix, roll back)
VERDICT: hold                   (the evidence speaks to the question but says wait: conflicting, outdated, or "not yet")
VERDICT: insufficient_evidence  (nothing you know or were given answers this question)

A source about the product that does not address the question is still insufficient.
If you are torn, it is insufficient_evidence.
"""


def prompt_for(row: dict, pooled: bool) -> str:
    """Closed: what a user would type. Pooled: plus the same evidence our system sees."""
    context = f"Context: {row['context']}\n" if row.get("context") else ""
    evidence = ""
    if pooled:
        docs = "\n".join(f"- [{d.get('doc_id')}] ({d.get('source', '')}, {d.get('date', '')}) "
                          f"{d.get('title', '')}: {d.get('text', '')}"
                          for d in row.get("evidence", []))
        evidence = f"Evidence (use only this):\n{docs or '(none)'}\n"
    return PROMPT.format(query=row["query"], context=context, evidence=evidence)


_CATALOG = None


def _grounded_vendors(query: str) -> list:
    """The vendors the marag_decide arm would use (eval_harness/generators.py)."""
    global _CATALOG
    import grounding
    import vendor
    if _CATALOG is None:
        _CATALOG = vendor.load_catalog(fetch=False)
    return grounding.ground(query, catalog=_CATALOG).vendor_names


def ours(row: dict) -> Optional[str]:
    """decide() on the row's pool with the arm's grounded vendors. The pool is the
    sheet's union of every arm's documents, the same one the annotators and LLMs see."""
    d = decide(row.get("evidence", []), row["query"], vendors=_grounded_vendors(row["query"]))
    return COLLAPSE[d.verdict]


def llm_system(spec: str, pooled: bool) -> Optional[Callable[[dict], Optional[str]]]:
    """None when the backend has no key / SDK, so the caller can report it skipped."""
    load_dotenv()
    client = make_client(spec)
    if not client.available():
        return None

    def ask(row: dict) -> Optional[str]:
        for _ in range(2):  # one retry: rate limits are transient
            try:
                # 4096: gemini-2.5 spends thinking tokens out of this budget
                return parse_verdict(client.generate(prompt_for(row, pooled), max_tokens=4096))
            except LLMError:
                continue
        return ERROR
    return ask


# (sheet ecosystem, sheet vendor) -> OSV package name. Empty on purpose: the
# decision sheet names ecosystems ("npm / Node.js"), never a package, so a
# scanner has nothing to look up. Add rows only for questions that name one.
OSV_PACKAGES: dict = {}
# Sheet ecosystem -> OSV ecosystem. Everything else is outside what a scanner sees.
OSV_ECOSYSTEMS = {"npm_node": "npm", "pip_python": "PyPI", "cargo_rust": "crates.io",
                  "debian": "Debian", "ubuntu": "Ubuntu", "android": "Android",
                  "linux_kernel": "Linux"}
_VERSION = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")


def _osv_query(package: str, ecosystem: str, version: Optional[str]) -> list:
    body = {"package": {"name": package, "ecosystem": ecosystem}}
    if version:
        body["version"] = version
    req = urllib.request.Request("https://api.osv.dev/v1/query", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("vulns", [])


def osv(row: dict) -> Optional[str]:
    """act if OSV lists a vuln (apply the fix, as decide's patch_urgently does),
    insufficient_evidence if it lists none (a clean scan says nothing about
    waiting), None when there is no package to scan or the lookup failed."""
    eco = OSV_ECOSYSTEMS.get(row.get("ecosystem", ""))
    package = OSV_PACKAGES.get((row.get("ecosystem", ""), row.get("vendor", "")))
    if not eco or not package:
        return None
    m = _VERSION.search(row["query"])
    try:
        vulns = _osv_query(package, eco, m.group(0) if m else None)
    except (OSError, ValueError):
        return None
    return "act" if vulns else "insufficient_evidence"


# --- run + report -----------------------------------------------------------

LLM_RUNS = [("ollama:llama3.1", False), ("openai:gpt-4o-mini", False), ("openai:gpt-4o-mini", True),
            ("gemini:gemini-2.5-flash", False), ("gemini:gemini-2.5-flash", True)]


def systems() -> tuple[dict, list]:
    """name -> fn for every runnable system, plus the names that were skipped."""
    run, skipped = {"ours (decide, grounded vendors)": ours, "osv scanner": osv}, []
    for spec, pooled in LLM_RUNS:
        name = f"{spec} ({'pooled' if pooled else 'closed'})"
        fn = llm_system(spec, pooled)
        if fn:
            run[name] = fn
        else:
            skipped.append(name)
    return run, skipped


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def report(sheet: str, gold_rows: list, preds: dict, skipped: list, n_total: int) -> str:
    from build_decision_benchmark import file_hash
    gold = [r["gold"] for r in gold_rows]
    lines = [f"# Head-to-head on `{sheet}` (sha1 {file_hash(sheet)})", "",
             f"Gold rows: {len(gold_rows)} of {n_total} (both annotators agree). "
             "Gold is labelled from each row's evidence pool, so *pooled* LLM runs are the "
             "like-for-like comparison; *closed* runs show what a user typing the question gets.", "",
             "| system | answered | accuracy (all rows) | accuracy (answered) | false green (answered holds) | abstain | unparsed | errors |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, pred in preds.items():
        s = score(gold, pred)
        answered = s["n"] - s["unparsed"] - s["errors"]
        lines.append(f"| {name} | {answered}/{s['n']} | {_pct(s['accuracy'])} | {_pct(s['accuracy_answered'])} | "
                     f"{_pct(s['false_green'])} ({s['n_hold']}) | {_pct(s['abstain'])} | {s['unparsed']} | {s['errors']} |")
    lines += [""] + [f"- skipped: {n} (no key or backend unavailable)" for n in skipped]
    lines += ["", "OSV `answered` is its coverage: it needs a package name, and these questions "
              "name products and ecosystems, not packages.",
              "`act` covers install, stay, apply a fix and roll back, so a false green is "
              "\"said act when the evidence says wait\", not only \"told to update\".",
              "`errors` are failed calls (rate limit, truncation), not model answers."]
    return "\n".join(lines) + "\n"


def main(argv: Optional[list] = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sheet")
    ap.add_argument("--out", help="markdown report path; per-row predictions go beside it as .jsonl")
    a = ap.parse_args(argv)
    gold_rows = load_gold(a.sheet)
    n_total = sum(1 for line in open(a.sheet) if line.strip())
    run, skipped = systems()
    rows_path = os.path.splitext(a.out)[0] + ".jsonl" if a.out else None
    if rows_path:
        os.makedirs(os.path.dirname(rows_path) or ".", exist_ok=True)
    preds: dict = {name: [] for name in run}
    # Row by row, each row appended and flushed as it finishes, so a crash keeps
    # what was paid for. A system that raises counts as an error on that row.
    with open(rows_path, "w") if rows_path else open(os.devnull, "w") as f:
        for r in gold_rows:
            row = {"id": r.get("id"), "gold": r["gold"]}
            for name, fn in run.items():
                try:
                    row[name] = fn(r)
                except Exception as e:  # noqa: BLE001 -- one bad row must not end the run
                    print(f"{name} failed on row {r.get('id')}: {e!r}", file=sys.stderr)
                    row[name] = ERROR
                preds[name].append(row[name])
            f.write(json.dumps(row) + "\n")
            f.flush()
    text = report(a.sheet, gold_rows, preds, skipped, n_total)
    print(text)
    if a.out:
        open(a.out, "w").write(text)


if __name__ == "__main__":
    main()
