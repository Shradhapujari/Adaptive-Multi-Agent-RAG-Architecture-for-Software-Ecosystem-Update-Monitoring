"""Print the full stored trace for one benchmark question, from a run directory.

Every example in the review deck's real-trace slides came out of this. It reads
only what a run already wrote -- pools.jsonl, per_query.jsonl, qrels.json -- so
it needs no model, no network, and it cannot drift from what was measured.

    python scripts/trace_question.py results/run_1790126271_8fda4edb2d21 44

With no question id it lists the questions whose pooled qrels span all three
source families (community / advisory / release), which is how q44 was found.

The quality recomputation mirrors EvaluatorAgent.run (multiagent_rag_v3.py):
overlap on title + subreddit + body, +3 for a verified source that matched at
least once, +5 for a verbatim 20-character prefix, best document over the
top-k, divided by the question's term count. It reproduces the run's logged
`self_quality`, which is the point -- if it ever stops reproducing it, the
scorer and the report have drifted apart.
"""
import json
import sys
from collections import defaultdict

VERIFIED = ("apple_rss", "cisa_kev", "circl_cve")
FAMILY = {"vendor_reddit": "community", "cisa_kev": "advisory", "cve": "advisory",
          "circl_cve": "advisory", "nvd": "advisory", "vendor_releases": "release",
          "releases": "release", "llm_releases": "release", "apple_rss": "release"}


def load(run_dir):
    docs, arms = {}, defaultdict(dict)
    with open(f"{run_dir}/pools.jsonl") as f:
        for line in f:
            r = json.loads(line)
            for d in r["docs"] + r.get("pool", []):
                if isinstance(d, dict) and "doc_id" in d:
                    docs[d["doc_id"]] = d
    with open(f"{run_dir}/per_query.jsonl") as f:
        for line in f:
            r = json.loads(line)
            arms[r["query_id"]][r["system"]] = r
    with open(f"{run_dir}/qrels.json") as f:
        qrels = json.load(f)
    return docs, arms, qrels


def quality(question, doc_ids, docs):
    """EvaluatorAgent's score, recomputed. Returns (raw_ratio, per-document hits)."""
    terms = set(question.lower().split())
    rows = []
    for did in doc_ids:
        d = docs.get(did)
        if not d:
            continue
        txt = (d.get("title", "") + " " + d.get("subreddit", "") + " " + d.get("text", "")).lower()
        overlap = terms & set(txt.split())
        hits = len(overlap)
        if d.get("source") in VERIFIED and hits >= 1:
            hits += 3
        if question.lower()[:20] in txt:
            hits += 5
        rows.append((did, hits, sorted(overlap)))
    best = max((h for _, h, _ in rows), default=0)
    return round(min(best / max(len(terms), 1), 1.0), 2), rows


def spanning(arms, qrels, docs):
    """Question ids whose pooled judgements cover all three source families."""
    out = []
    for qid in arms:
        fams = {FAMILY.get(docs[d]["source"]) for d in qrels.get(str(qid), {}) if d in docs}
        if len({f for f in fams if f}) == 3:
            out.append(qid)
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run_dir = sys.argv[1].rstrip("/")
    docs, arms, qrels = load(run_dir)

    if len(sys.argv) < 3:
        ids = spanning(arms, qrels, docs)
        print(f"{len(ids)} of {len(arms)} questions span community + advisory + release:")
        for qid in ids[:40]:
            print(f"  q{qid:<4} {next(iter(arms[qid].values()))['query'][:78]}")
        return

    qid = int(sys.argv[2])
    graded = qrels.get(str(qid), {})
    question = next(iter(arms[qid].values()))["query"]
    print(f"q{qid}: {question}\n")

    for system, r in sorted(arms[qid].items()):
        raw, rows = quality(question, r["doc_ids"], docs)
        print(f"{system}  pool={r['pool_size']}  logged self_quality={r['self_quality']}  "
              f"recomputed raw={raw:.2f}")
        for i, (did, hits, overlap) in enumerate(rows, 1):
            d = docs[did]
            print(f"  {i}. grade {graded.get(did, '?')}  {d['source']:16} hits={hits:<3} "
                  f"overlap={overlap}")
            print(f"     {d.get('title', '')[:88]}")
            if d.get("url"):
                print(f"     {d['url'][:88]}")
        print()
if __name__ == "__main__":
    main()
