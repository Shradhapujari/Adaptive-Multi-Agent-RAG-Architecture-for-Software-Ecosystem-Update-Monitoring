# Pipeline — execution graph, state, contracts, failure policy

The analogue of an execution graph for this project: what runs in what order, what
each stage is allowed to assume about its input, and what it must report about
itself. Contracts here are the interface between the pipeline and the harness;
changing one means editing this file in the same commit.

---

## 1. Graph

```
  user question q
        │
        ▼
  ┌───────────────────────┐
  │ A1  Query Rewriter    │  llama3.1, temperature 0
  │  q ──► q'             │  "rewrite to document vocabulary, <20 words"
  └───────────────────────┘
        │  {original: q, rewritten: q'}
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ A2  Retriever                                               │
  │                                                             │
  │  ── STEP 1/2  vendor detection ──► vendor_releases,         │
  │                                    vendor_reddit            │
  │                                                             │
  │  ── STEP 3  source fan-out, run for BOTH phrasings ──       │
  │      for s in [q', q]:            ◄── DEFECT 1 FIXED HERE   │
  │          releases, apple RSS, CISA KEV, CIRCL, CVE,         │
  │          LLM feed (gated), reddit, google news              │
  │                                                             │
  │  ── tiering ──                                              │
  │      tier1 = dedupe(vendor_releases + verified sources)     │
  │      tier2 = dedupe(vendor_reddit + community, seen=tier1)  │
  │      pool  = tier1 + tier2            ◄── LOGGED as `pool`  │
  │                                                             │
  │  ── ranking, per tier, against q NOT q' ──                  │
  │      MARAG_RERANK ∈ {none, bm25, embed} ◄ DEFECT 2 FIXED    │
  │      results = rank(tier1) + rank(tier2)                    │
  └─────────────────────────────────────────────────────────────┘
        │  results[:top_k]
        ▼
  ┌───────────────────────┐
  │ A3  Evaluator (RLAIF) │  self-scores retrieval quality,
  │                       │  assembles the template answer
  └───────────────────────┘
        │
        ▼
     answer + docs + self_quality
```

**Baseline (`single_agent`)** takes the same `RetrieverAgent` with `q` passed as both
the rewritten and the original query, so the union collapses to a single search, and
synthesises with one LLM call. It shares the reranker. That sharing is the reason
`single_agent` is **not** a rerank-independent control — see §5.

## 2. Why the graph looks like this — the two defects

Both are measured in `eval_harness/FINDINGS.md` and both carry regression tests.

**Defect 1 — the rewrite replaced the search string (fetch-time loss).**
Every live endpoint was queried with `q'` only. Counted on the 10-question set,
**22 of 23** relevant documents the baseline retrieved were never fetched by the
multi-agent arm at all. No reranker can promote a document that is not in the pool.
Fix: search both phrasings and union the pools, deduped by URL.

| Configuration | marag nDCG@3 | marag MRR | marag recall@5 |
|---|---:|---:|---:|
| `embed`, rewrite replaces query | 0.188 | 0.625 | 0.327 |
| `embed`, rewrite augments query | **0.973** | **1.000** | **0.933** |

**Defect 2 — ranking scored against the rewrite (ranking-time loss).**
Final ordering was a substring boost over the first four tokens of `q'`; after a
rewrite those tokens are filler. Fix: fetch with `q'` for recall, rank against `q` for
precision. `rerank.py` makes the backend an experimental variable rather than an
assumption, and keeps `none` as the arm that reproduces the original behaviour.

## 3. Data contracts

**Document** — what every source adapter must emit, and what the harness normalises.

```python
{"doc_id": str,     # sha1(url or title|source)[:12]  — stable, the qrels key
 "title": str, "text": str, "source": str, "url": str,
 "subreddit": str, "date": str}
```

`doc_id` is derived from the URL when present. Two sources surfacing the same URL are
one document; `dedupe_docs` relies on this, and so does every recall denominator.

**Generator output** — the contract between a system under test and the harness.

```python
{"answer": str,
 "docs": [doc, ...],          # ranked, cut to top_k
 "pool": [doc, ...],          # pre-rerank candidates; [] for retrieval-free arms
 "self_quality": float|None,
 "rerank_spec": str,          # the backend that actually ran
 "rerank_degraded": bool}     # true if it fell back
```

`pool` is the diagnostic that makes "buried by ranking" and "never fetched"
distinguishable from artifacts alone. Its absence is what made the 2026-08-30 sweep
un-analysable after the fact.

**Retriever diagnostics** — set on the agent instance by every `run()`:
`last_pool`, `last_rank_query`, `last_rerank_spec`, `last_rerank_degraded`.
Declared as class attributes so a caller can read them after an early return.

## 4. Failure and degradation policy

Retrieval must never take a run down, and a degradation must never be invisible.

| Failure | Behaviour | Reported as |
|---|---|---|
| Embedding backend unavailable at build time | Build BM25 instead | `spec = "bm25(fallback from embed:<model>)"`, `degraded = True` |
| Embedding call raises mid-run (timeout, reset) | Rank with BM25 for that call | printed warning; run continues |
| BM25 also raises | Keep the retriever's own order | printed warning |
| All live sources return nothing | Fall back to the local `DOCS` dataset | printed; answer header says "From local dataset" |
| Replay miss on a document host | Go live, record, count | `corpus_misses > 0`, `frozen: false`, WARNING printed |
| Replay miss on a model host | Go live, record, count | counted but does not void the run |
| Unknown `MARAG_RERANK` value | Raise | run aborts — a typo must not quietly measure the wrong arm |

The asymmetry in the last three rows is deliberate. A missing *document* voids a
cross-arm comparison; a missing *model call* does not, because arms legitimately make
different model calls — the embed arm queries an embeddings endpoint the `none` arm
never touches.

## 5. Controls, and the one we do not have

`single_agent` differs from `marag` in the rewrite and the answer path. It shares the
retriever, the source adapters, and the reranker. Therefore:

- It **is** a valid control for the rewrite (C1, C2). Union fetch collapses to a
  single search for it, so a before/after on union fetch is clean for the marag arm.
- It is **not** a control for the ranking backend. Both arms move when
  `MARAG_RERANK` changes, so a difference-in-differences across arms measures nothing.

The only control for corpus drift is `MARAG_CORPUS=replay:<dir>`. Without it, two runs
minutes apart returned a different document set on 10 of 10 questions for the same
question and the same system. Any cross-arm table built on live runs is void.

## 6. Cost model

Per question, arm `embed`, measured on the reference machine.

| Stage | Calls | Typical |
|---|---|---|
| Rewrite | 1 × llama3.1 | ~2 s |
| Source fan-out | ~8 endpoints × 2 phrasings | dominated by network |
| Reranking (`embed`) | 1 query + |pool| document embeddings, memoised per process | pool is 9–21 documents |
| Answer | 1 × llama3.1 (template arm does 0) | ~3 s |
| **marag total** | | **~20–23 s** |
| **single_agent total** | | **~12–17 s** |

Union fetch roughly doubles the fan-out. That cost is the price of C2 and belongs in
the paper next to the gain.


## 7. Modules added since the n=300 run

Five modules landed in Week 3 (PRs #18–#21). Grouped by the only distinction that
matters for this file: whether a change to one can move a published number.

| Module | Imported by | On the measured path | What it does |
|---|---|:--:|---|
| `yesno.py` | `app_1.py`, `scripts/eval_yesno.py` | no | Counts a thread's commenters for a question that takes a one-word answer |
| `survey.py` | `app_1.py` | no | Weights the app's quality score by the n=52 survey's user priorities |
| `xai.py` | `app_1.py` | no | Reasoning trace: why each source was retrieved, which claim rests on which |
| `guardrail.py` | `answer_agent.py`, `xai.py` | no | Refuses a presented answer the evidence does not carry |
| `model_select.py` | `answer_agent.py` | no | Picks the presenter model by role and reachability |
| `agent_rules.py` | `multiagent_rag_v3.py`, `answer_agent.py`, `app_1.py` | **yes** | Prepends `AGENT_RULES.md` to every prompt |

### 7.1 Demo-only stages

`yesno`, `survey` and `xai` run inside `app_1.py` only. No generator in
`eval_harness` imports them, so they cannot move a retrieval or faithfulness
number, and a change to one needs no re-run. `app_1`'s own graph — temporal
grounder, vendor/intent grounder, three source agents, presenter — is not the
graph in §1; §1 is the harness's path through `multiagent_rag_v3`. The two
share `grounding.ground` and `rerank`, and nothing else.

The yes/no stage has its own retrieval: `/api/reddit/query/questions`, which
returns comments inline, ranked with the same `BM25Reranker` §1 uses. It is
gated on `looks_yesno(query, is_title=True)` and reports a count, never a
synthesised claim. Measured in `scripts/eval_yesno.py` against a frozen
snapshot — see `specs/status.md` §11.5 for the figures and their two caveats.

### 7.2 Presenter path

`answer_agent.present_answer` is imported by `app_1.py` and by nothing in
`eval_harness`. The harness scores `build_synthesis_prompt`, which is
deliberately unmodified (see the module docstring). So both of these change what
the demo prints and leave the published faithfulness numbers alone:

- **`guardrail.check(answer, evidence) -> Verdict`** — checks the generated
  paragraph against the same evidence list the prompt was built from: versions,
  dates and citation labels that appear in the answer must appear in the
  evidence. Rule-based, for the same reason `yesno` is: the deployed host may
  have no model, and a checker that needs one is off exactly when the fallback
  prose is showing. An abstention is in bounds by construction — declining to
  answer can never be a grounding violation — but only as far as
  `benchmarks.is_abstention` recognises one: "The sources do not answer this
  question." passes, "I could not find anything in the sources that answers
  this." does not, and is then judged as an assertion. That recognition is
  narrow and is being widened on `fix/guardrail-bare-integers-and-weak-abstention`;
  until it lands, a refusal phrased outside the pattern is scored as a
  violation. Every violation names its offending span.
- **`model_select.select(role) -> Choice`** — probes reachability rather than
  trusting a configured spec, and can exclude a model family so a judge does not
  share one with a system under test (threat T2, `evaluation-protocol.md`). The
  registry is a literal table; costs only break ties.

### 7.3 `AGENT_RULES.md` is a prompt input, and it *is* on the measured path

`agent_rules.rules_block()` is prepended inside `multiagent_rag_v3.call_llama`,
which both `QueryRewriterAgent` and `EvaluatorAgent` call. The harness's marag
arms use both agents, and `render_template` runs `EvaluatorAgent.run`. So a
markdown file outside the code is now part of the prompt of every measured arm
that calls a model.

That is a deliberate feature — behaviour changes with no code change — and it is
also a new way for a comparison to go silently wrong. Three consequences:

1. **The published n=300 numbers (§10.1 of `status.md`) predate it.** They were
   produced with prompts that carried no rules block. Any new run is not
   comparable to them on the answer-quality metrics without saying so.
2. **A run's provenance must record the file.** `results/PROVENANCE.md` records
   corpus, models and reranker; it has no field for prompt inputs. Until it
   does, the hash of `AGENT_RULES.md` at run time is unrecorded and a run cannot
   be reproduced from the artifacts alone.
3. **Replay keyed on prompt text will miss** on every model call after the file
   changes, and per §4 a model-host miss is counted but does not void the run —
   so this failure is quiet by design. That policy was written for arms that
   legitimately differ; a rules edit is not that.

Editing `AGENT_RULES.md` between two runs is therefore an experimental change,
not a documentation change, and belongs in the same commit as this file per the
contract note at the top.
