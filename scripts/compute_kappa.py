"""Agreement on an annotation sheet: Cohen's kappa with a bootstrap CI.

    python scripts/compute_kappa.py data/calibration_100.jsonl relevance \
        --judge data/calibration_100.judge.json
    python scripts/compute_kappa.py data/decision_benchmark_200.jsonl verdict

The sheet is JSONL with `a1` and `a2` blocks holding the field named on the
command line. Rows either annotator left null are skipped and counted.
Reported: a1-a2 kappa, and with --judge each annotator against the judge's
key and the judge against the rows where the annotators agree (the gold the
judge is meant to reproduce). Ordinal fields (0/1/2) also get the
quadratic-weighted kappa, which forgives 1-vs-2 more than 0-vs-2.

Per-stratum rows follow, on `asks` and `tier` when present. Strata under
--min-n (default 15) print their n and no kappa: a kappa on 3 pairs is a
coin toss with a confidence interval, and we would rather say "3 pairs".

A decision sheet is also checked for its evidence obligation: a verdict
other than insufficient_evidence must cite at least one doc_id from the
row's pool, and only ids from it. Violations are sheet errors, listed first.

Bootstrap: 2000 resamples of the rows, seed 0, percentile 95% CI.
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict

B, SEED, MIN_N = 2000, 0, 15


def kappa(a, b, weighted=False):
    """Cohen's kappa; quadratic weights when `weighted` and labels are ints."""
    n = len(a)
    if n == 0:
        return None
    cats = sorted(set(a) | set(b), key=lambda x: (str(type(x)), x))
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[idx[x]][idx[y]] += 1
    ra = [sum(r) for r in obs]
    cb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    if weighted:
        w = [[((i - j) ** 2) / max((k - 1) ** 2, 1) for j in range(k)] for i in range(k)]
    else:
        w = [[0 if i == j else 1 for j in range(k)] for i in range(k)]
    po = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w[i][j] * ra[i] * cb[j] for i in range(k) for j in range(k)) / (n * n)
    return 1.0 if pe == 0 else 1 - po / pe


def ci(a, b, weighted=False):
    rng = random.Random(SEED)
    n = len(a)
    ks = []
    for _ in range(B):
        ix = [rng.randrange(n) for _ in range(n)]
        v = kappa([a[i] for i in ix], [b[i] for i in ix], weighted)
        if v is not None:
            ks.append(v)
    ks.sort()
    return ks[int(0.025 * len(ks))], ks[int(0.975 * len(ks)) - 1]


def report(name, a, b, ordinal):
    n = len(a)
    if n < MIN_N:
        print(f"  {name:<34} n={n:<4} (below --min-n, no kappa)")
        return
    k = kappa(a, b); lo, hi = ci(a, b)
    line = f"  {name:<34} n={n:<4} kappa={k:+.3f} [{lo:+.3f}, {hi:+.3f}]"
    if ordinal:
        kw = kappa(a, b, True); wlo, whi = ci(a, b, True)
        line += f"  weighted={kw:+.3f} [{wlo:+.3f}, {whi:+.3f}]"
    print(line + f"  raw agreement={sum(x == y for x, y in zip(a, b)) / n:.2f}")


def obligation_errors(rows, field):
    errs = []
    for r in rows:
        pool = {d.get("doc_id") for d in r.get("evidence", [])}
        for who in ("a1", "a2"):
            blk = r.get(who) or {}
            v, ids = blk.get(field), blk.get("evidence_doc_ids") or []
            if v is None:
                continue
            if v != "insufficient_evidence" and not ids:
                errs.append(f"row {r['id']} {who}: {v} cites no evidence")
            if v == "insufficient_evidence" and ids:
                errs.append(f"row {r['id']} {who}: insufficient_evidence cites {ids}")
            bad = [i for i in ids if i not in pool]
            if bad:
                errs.append(f"row {r['id']} {who}: ids not in pool {bad}")
    return errs


def main():
    global MIN_N
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet"); ap.add_argument("field")
    ap.add_argument("--judge", help="JSON {row id: label} the humans were blind to")
    ap.add_argument("--min-n", type=int, default=MIN_N)
    args = ap.parse_args()
    MIN_N = args.min_n

    rows = [json.loads(l) for l in open(args.sheet) if l.strip()]
    judge = {str(k): v for k, v in json.load(open(args.judge)).items()} if args.judge else None
    labelled = [r for r in rows if (r.get("a1") or {}).get(args.field) is not None
                and (r.get("a2") or {}).get(args.field) is not None]
    print(f"{args.sheet}: {len(rows)} rows, {len(labelled)} labelled by both, "
          f"{len(rows) - len(labelled)} skipped")
    if "evidence" in (rows[0] if rows else {}):
        errs = obligation_errors(rows, args.field)
        print(f"evidence obligation: {len(errs)} error(s)")
        for e in errs[:30]:
            print("  !", e)
    if not labelled:
        return
    a1 = [r["a1"][args.field] for r in labelled]
    a2 = [r["a2"][args.field] for r in labelled]
    ordinal = all(isinstance(x, int) for x in a1 + a2)
    print("label counts a1:", dict(sorted(Counter(a1).items(), key=str)),
          " a2:", dict(sorted(Counter(a2).items(), key=str)))

    def block(title, rs, fn):
        print(title)
        report("all", *fn(rs), ordinal)
        for strat in ("asks", "tier"):
            if strat in rs[0]:
                groups = defaultdict(list)
                for r in rs:
                    groups[r[strat]].append(r)
                for g, grs in sorted(groups.items()):
                    report(f"  {strat}={g}", *fn(grs), ordinal)

    block("a1 vs a2", labelled, lambda rs: ([r["a1"][args.field] for r in rs], [r["a2"][args.field] for r in rs]))
    if judge:
        jl = [r for r in labelled if str(r["id"]) in judge]
        block("a1 vs judge", jl, lambda rs: ([r["a1"][args.field] for r in rs], [judge[str(r["id"])] for r in rs]))
        block("a2 vs judge", jl, lambda rs: ([r["a2"][args.field] for r in rs], [judge[str(r["id"])] for r in rs]))
        agreed = [r for r in jl if r["a1"][args.field] == r["a2"][args.field]]
        print(f"judge vs human-agreed gold ({len(agreed)} of {len(jl)} rows agreed)")
        block("", agreed, lambda rs: ([r["a1"][args.field] for r in rs], [judge[str(r["id"])] for r in rs]))


if __name__ == "__main__":
    main()
