"""Label a decision sheet one row at a time, in the terminal.

    venv311/bin/python scripts/annotate.py ~/annot_a1.jsonl a1 --rows 30

Shows each row you have not labelled yet: the question, its context, and the
evidence pool numbered 1..n. You answer with a verdict and the numbers of the
documents it rests on; the script writes your block (`a1` or `a2`) with the
real doc_ids and saves the file after every row, so quitting loses nothing.

It never shows the other annotator's block or the system's verdict, and it
refuses a label that breaks the evidence obligation compute_kappa.py checks:
act/hold cite at least one document from this row's pool, and
insufficient_evidence cites none.

At the verdict prompt a number shows that document in full.
"""
import argparse
import json
import os
import sys
import textwrap

VERDICTS = {"a": "act", "h": "hold", "i": "insufficient_evidence"}


def block(row: dict, verdict: str, picks: list, note: str = "") -> dict:
    """The annotator block for `row`, or ValueError if it breaks the rules.
    `picks` are 1-based positions in the row's evidence list."""
    if verdict not in VERDICTS.values():
        raise ValueError(f"verdict must be one of {sorted(VERDICTS.values())}")
    pool = row.get("evidence") or []
    if any(not 1 <= p <= len(pool) for p in picks):
        raise ValueError(f"document numbers run 1..{len(pool)}")
    if verdict == "insufficient_evidence" and picks:
        raise ValueError("insufficient_evidence cites no documents")
    if verdict != "insufficient_evidence" and not picks:
        raise ValueError(f"{verdict} needs at least one document number")
    ids = list(dict.fromkeys(pool[p - 1]["doc_id"] for p in picks))
    return {"verdict": verdict, "evidence_doc_ids": ids, "note": note}


def save(path: str, rows: list) -> None:
    """Write the sheet atomically: a crash mid-write leaves the old file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _show_doc(i: int, d: dict, width) -> str:
    text = " ".join((d.get("text") or "").split())
    if width and len(text) > width:
        text = text[:width] + " …"
    head = f"[{i}] {d.get('title') or '(no title)'}"
    meta = " · ".join(x for x in (d.get("source"), d.get("date")) if x)
    body = textwrap.fill(text, 100, initial_indent="     ", subsequent_indent="     ") if text else ""
    return "\n".join(x for x in (head, f"     {meta}" if meta else "", body) if x)


def _show_row(r: dict, n: int, total: int, width) -> str:
    out = ["", "=" * 100, f"Row id {r['id']} · {n} of {total} · asks: {r.get('asks')} · "
           f"{r.get('ecosystem')}", "", f"Q: {r['query']}"]
    if r.get("context"):
        out.append(textwrap.fill(" ".join(str(r["context"]).split())[:800], 100,
                                 initial_indent="   ", subsequent_indent="   "))
    out += ["", f"Evidence ({len(r.get('evidence') or [])} documents):"]
    out += [_show_doc(i, d, width) for i, d in enumerate(r.get("evidence") or [], 1)]
    return "\n".join(out)


def run(path: str, who: str, limit=None, width=300, ask=input, say=print) -> int:
    """Label until done or quit; returns how many rows were labelled."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    scope = rows[:limit] if limit else rows
    todo = [r for r in scope if not (r.get(who) or {}).get("verdict")]
    say(f"{path}: {len(scope) - len(todo)} of {len(scope)} rows already labelled by {who}")
    done = 0
    for n, r in enumerate(todo, 1):
        say(_show_row(r, n, len(todo), width))
        pool = r.get("evidence") or []
        while True:
            ans = ask("\nverdict [a]ct [h]old [i]nsufficient, a number to read a document, "
                      "[s]kip, [q]uit: ").strip().lower()
            if ans == "q":
                say(f"saved; labelled {done} this session")
                return done
            if ans == "s":
                break
            if ans.isdigit():
                k = int(ans)
                say(_show_doc(k, pool[k - 1], None) if 1 <= k <= len(pool)
                    else f"documents run 1..{len(pool)}")
                continue
            if ans not in VERDICTS:
                continue
            verdict = VERDICTS[ans]
            picks = []
            if verdict != "insufficient_evidence":
                raw = ask("documents it rests on (numbers, e.g. 1 4 7): ")
                try:
                    picks = [int(x) for x in raw.replace(",", " ").split()]
                except ValueError:
                    say("numbers only")
                    continue
            try:
                blk = block(r, verdict, picks, ask("note (optional): ").strip())
            except ValueError as e:
                say(f"not saved: {e}")
                continue
            r[who] = blk
            save(path, rows)
            done += 1
            break
    say(f"done; labelled {done} this session")
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sheet", help="your private copy, e.g. ~/annot_a1.jsonl")
    ap.add_argument("who", choices=("a1", "a2", "gold"))
    ap.add_argument("--rows", type=int, help="only the first N rows (the pilot is 30, then 50)")
    ap.add_argument("--width", type=int, default=300,
                    help="characters of each document to show (0 = all)")
    a = ap.parse_args()
    try:
        run(os.path.expanduser(a.sheet), a.who, a.rows, a.width or None)
    except (KeyboardInterrupt, EOFError):
        print("\nstopped; every finished row is saved")
        sys.exit(130)


if __name__ == "__main__":
    main()
