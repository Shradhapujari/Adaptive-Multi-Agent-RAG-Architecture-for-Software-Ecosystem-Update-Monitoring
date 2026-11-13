# Architecture

Four specialized agents coordinated by a Manager (the Orchestrator in the
paper), connected by a retrieval-level feedback loop. Two further agents were
added to the demo pipeline after the evaluation was complete, and are marked as
such throughout — no reported number depends on them.

```
                       ┌──────────────────────┐
                       │    User question     │
                       └──────────┬───────────┘
                                  ▼
                       ┌──────────────────────┐
                       │  Temporal Grounder   │  (post-evaluation)
                       │  "today" → a date    │
                       └──────────┬───────────┘
                                  ▼
                       ┌──────────────────────┐
                       │    Manager Agent     │
                       └──────────┬───────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ Query Rewriter │─────▶│    Retriever     │─────▶│    Evaluator     │
│  (Llama 3.1)   │      │ union fetch +    │      │  score 0.0–1.0   │
└────────────────┘      │ vendor-aware     │      └────────┬─────────┘
        ▲               └──────────────────┘               │
        │        widen the fetch on a negative signal      │
        └─────────────────────────────────────────────────-┘
                                  ▼
                       ┌──────────────────────┐
                       │   Answer Presenter   │  (post-evaluation)
                       │  prose + citations   │
                       └──────────────────────┘
```

## The four evaluated agents

### Query Rewriter
Normalizes user terminology toward the vocabulary of technical documents, using
a local Llama 3.1 call and degrading to rule-based expansion when no model is
reachable. Pulls from the Self-Improvement Memory to bias future queries toward
terms that have led to successful retrievals.

**The defect that made this project a negative result lived here** — not in the
rewriting itself, but in how its output was used. See
[Evaluation and Findings](Evaluation-and-Findings.md).

### Retriever
Vendor-aware search across a registry of 14,223 vendors and 628
software-related subreddits, restricting retrieval to vendor-specific sources
when a vendor is detected. Two properties matter:

- **Union fetch.** Both the original phrasing and the rewritten one are issued
  to every endpoint and the candidate pools are unioned. Ablatable via
  `union=False` on the generator — kept as an arm, not deleted.
- **Ranking against the original question.** Candidates are reranked by
  `rerank.py`, selected with `MARAG_RERANK=none|bm25|embed`. `none` reproduces
  the published substring boost and is kept deliberately as the ablation arm;
  `embed` degrades to `bm25` *and reports that it did so*, rather than silently
  measuring something other than what it claims.

### Evaluator
A deterministic 0.0–1.0 score over retrieval volume, release-note matches,
community matches and CVE matches, emitting an RLAIF-style positive/negative
signal. Note a discrepancy worth knowing: the negative signal fires at quality
**< 0.15**, not the 0.30 the earlier write-up quotes — 0.30 is a different
constant in the same method (a quality floor for tier-1 and Apple sources).

### Manager
Plans the pipeline and, on a negative Evaluator signal, sends the Retriever back
with a widened fetch while still ranking against the user's own words. Its
recursion guard is literally `"retry" not in query`, which also means a question
containing the word *retry* never triggers one.

## Self-Improvement Memory

Every query-expansion term that leads to a successful retrieval accumulates a
positive score; failed retrievals decrement. No human feedback, no labelled
data, no retraining. Top learned terms after 50 queries: `vulnerability`
(+2.20), `patch` (+1.58), `advisory` (+1.23), `update` (+1.15), `kernel`
(+0.98).

The **+9.3%** improvement attributed to this mechanism compares time-ordered
tertiles against a live corpus that drifts during the run, so adaptation is not
separable from drift. Mechanism sound, magnitude unestablished.

---

## Added after the evaluation

### Temporal Grounder — `temporal.py`

Retrieval is similarity-based, and no document contains the word *today* — it
contains a date. A question like *"Any critical Linux updates today?"* therefore
carries its most restrictive constraint in a token that cannot match anything,
and the system answers the untimed question instead.

The Grounder resolves relative expressions to absolute ones **before** retrieval,
in both the human and the ISO form so that lexical and embedding scorers each
have something to match:

```
Any critical Linux updates today?
  → Any critical Linux updates on Aug 31, 2026 (2026-08-31)?
```

Covers today / yesterday / tomorrow, this-and-last week / month / year, "in the
past N days", "recently", "currently". Version ordinals — *latest*, *newest*,
*current* — are deliberately left alone: they are ordinal over releases, not
deictic over dates, and pinning *"Latest Django release notes"* to today's date
narrows it to nothing.

It is rule-based and clock-injected rather than an LLM call, for three reasons:
the arithmetic is exact and a model gets it wrong whenever its idea of the
current date differs from the host's; the deployed host has no model; and a
date-dependent test cannot detect a regression in a date-dependent bug.

### Union of every phrasing — `fetch_union.py`

Grounding the date into the **fetch** is the trap, and it is measured. The
release endpoint matches `q` against product names, not free text:

| `q` | releases returned |
|---|---:|
| `Linux` | 606 |
| `critical Linux updates` | 0 |
| `Any critical Linux updates on Aug 31, 2026 (2026-08-31)?` | 0 |

So fetching only the grounded phrasing took the release agent from five results
to none, on exactly the questions the Grounder exists to help. The fetch now
runs every phrasing — rewritten, plain, dated, and the extracted product term —
unions and dedupes them, and uses the resolved window to **rank rather than
filter**: out-of-window results are kept and ranked last, so a quiet day still
returns something to read.

Dates in the feeds arrive in more than one format (`20260828` from
`versionReleaseDate`, `2026-08-31T04:00:00Z` from `created_utc`); parsing only
the ISO form reported every release as undated.

### Answer Presenter — `answer_agent.py`

Turns retrieved documents into one readable paragraph with each claim cited in
brackets, replacing the assembled bullet template as what the demo shows:

> 2 of the 2 releases matching this question for Aug 31, 2026 are classified as
> security fixes: Linux v6.18.21 **[Release Notes - Linux v6.18.21,
> 2026-08-28]** …

It reuses the harness's provider layer (`eval_harness/providers.py`) and its
shared grounding instruction, extended with a citation rule. The harness's
`build_synthesis_prompt` is **untouched** — the published answer-quality numbers
were produced with that prompt verbatim.

With no model reachable it composes the same shape by rule, and the UI states
which path produced the text, so rule-based prose is never passed off as model
output.

### Decision gate — `decide.py`, `graph.py`

Fourteen findings say every arm retrieves the same documents, so retrieval
metrics cannot separate architectures. The console therefore changes the output
type: not a paragraph over the top-k but a *verdict*, each carrying the
rule-checkable evidence it needs before it may be issued. Precedence is the
table's order:

| Verdict | Obligation checked against the pool |
|---|---|
| `patch_urgently` | An advisory-tier document (CISA KEV / CVE feed) *for that product*, with a CVE id, matching the asked version if one is asked |
| `hold` | At least K community problem reports on the product/version, and no newer vendor release that says it is fixed |
| `update_with_caveat` | A release note naming a breaking change, deprecation or known issue (or reports a newer release fixed) |
| `safe` | A release note, no advisory, fewer than K reports, no caveat |
| `insufficient_evidence` | None of the above holds: abstain |

It is model-free on purpose: it must run when Ollama is down, and only fields
extracted from a document (source class, CVE ids, versions, dates, markers)
reach the verdict, never its prose, so an injected instruction inside a Reddit
post is irrelevant to the decision. Advisories are attributed by owner: CISA KEV
rows by `vendorProject`/`product`, NVD text by the vendor named in the subject,
so a VMware "SD-WAN Edge" or Cisco "IOS" row does not turn Edge or iOS red.

`graph.py` walks it as a stdlib state machine
(`rewrite → retrieve → classify → {answer | verify | abstain | rewrite}`). The
edge out of `classify` depends on what the documents contain, the only way back
into `rewrite` is a failed fetch, and ABSENT on a healthy fetch is terminal. It
makes no model or network calls, so the eval harness can replay it byte-for-byte
as the `marag_decide` arm. LangGraph was evaluated and rejected: an unpinned
dependency tree under a replay-identical harness, for a graph with one cycle.

### Web fallback — `websearch.py` (GR-2)

The one orchestration-layer step off the local corpus: a single DuckDuckGo
search, at most `limit` results, run only after the graph returns ABSENT on a
healthy fetch. If the web is also empty of a verifiable version, date or CVE the
system still abstains. Off unless `MARAG_WEB_FALLBACK=1`.

### Egress and console guards

`guardrail.check` requires a CVE id in an answer to appear in a release note, an
advisory or the vendor's own page — forum posts, open-web snippets and the
question itself no longer vouch for one (the question still may in a refusal).
The console also declines off-topic questions before searching, offers "did you
mean" for typos, and shows no release headline unless the asked product has a
release.

---

## Implementations

| File | What it is |
|---|---|
| `multiagent_rag_v3.py` | Main four-agent system, pure Python — the cleanest execution trace |
| `eval_harness/generators.py` | Every evaluation arm, including the single-agent baseline |
| `app_1.py` | The deployed Streamlit demo (decision console by default) |
