# Writing Plan — ACM journal submission

Covers the paper's shape, the integrity practices that keep it defensible, and the
disclosure ACM requires. Phase 8 of `specs/roadmap.md` executes this.

---

## 1. The paper in one paragraph

Query rewriting is standard practice in RAG because it widens recall. We show a
concrete failure mode: when the rewrite *replaces* the user's query at fetch time
rather than augmenting it, retrieval collapses, and the loss is not recoverable by
better ranking because the relevant documents were never fetched. We measure the
failure on a live multi-source software-update corpus, isolate it to the fetch stage
by counting candidate-pool membership, and fix it with a union search that costs
roughly twice the fan-out. We also report that once the defect is fixed, our
multi-agent pipeline reaches parity with — and does not beat — a single-agent
baseline, and that the bespoke keyword-overlap score used in our earlier draft
contradicts standard IR metrics on the same runs.

The negative result belongs in the abstract. A paper that fixes its own headline
claim and says so is more useful, and more likely to survive review, than one that
quietly reframes.

## 2. Structure

| Section | Content | Depends on |
|---|---|---|
| 1 Introduction | The multi-source update-monitoring problem; why rewriting is the obvious move; what we found | — |
| 2 Related work | Query rewriting for recall; RAG evaluation; multi-agent retrieval; IR metric practice | — |
| 3 System | The three agents, the source fan-out, the tiering, the ranking stage (`specs/pipeline.md` §1) | Phase 1 |
| 4 Experimental setup | Datasets and provenance, judged relevance and its pooling bias, metrics and denominators, arms, statistical plan (`specs/evaluation-protocol.md`) | Phase 5 |
| 5 C1 — the fetch-time failure | Pool-membership count; why ranking cannot recover it; the ablation that separates fetch from rank | Phase 6 |
| 6 C2 — the union-fetch fix | Before/after on one frozen corpus; pool recall as mechanism; the cost | Phase 6 |
| 7 C3 — parity, not superiority | Negative result with CIs; latency cost | Phase 5 |
| 8 C4 — metric contradiction | Bespoke score vs nDCG/MRR on identical runs; retraction of +17.2 % | Phase 5 |
| 9 Threats to validity | All of `evaluation-protocol.md` §8, closed or declared | Phase 4 |
| 10 Conclusion | What transfers to other RAG systems | — |
| Artifact appendix | Reproduction steps, DOI, badges | Phase 7 |

## 3. Figures and tables

Every caption names the `run_id` its numbers came from. A figure whose provenance
cannot be stated does not go in the paper.

| # | Content | Source artifact |
|---|---|---|
| F1 | Pipeline graph, with the two defect sites marked | `specs/pipeline.md` §1 |
| T1 | Dataset composition and provenance mix | `data/benchmark_300.manifest.json` |
| T2 | Ranking ablation — three arms, frozen corpus, CIs | Phase 5 run dirs |
| T3 | Fetch mode — replace vs augment, same corpus | Phase 6 run dirs |
| F2 | Pool recall vs recall@5 per arm — the mechanism figure | `per_query.jsonl` |
| T4 | marag / marag_llm / single_agent, model held constant | Phase 5 step 2 |
| T5 | Judge agreement, local vs independent | Phase 4 |
| T6 | Latency and call counts per stage | `per_query.jsonl` |

## 4. Generative-AI disclosure

ACM's publication policy requires that use of generative AI in producing the work be
disclosed, and that AI systems are not listed as authors. Write the disclosure
specifically rather than generically — name what the tools did.

Draft, to be adjusted to what actually happened:

> Generative AI tools were used during this work in two distinct roles. First, as
> components of the system under study: Llama 3.1, Mistral, and nomic-embed-text run
> locally via Ollama perform query rewriting, answer synthesis, relevance judging, and
> embedding, as described in Section 3. Second, as engineering assistance: an AI coding
> assistant was used to implement and test parts of the evaluation harness and to help
> analyse result artifacts. All experimental design decisions, all interpretation of
> results, and all text in this paper are the authors'. The authors verified every
> reported number against the saved run artifacts and take full responsibility for the
> content.

Keep it accurate. An understated disclosure is a correctness problem, not a
presentational one.

## 5. Integrity practice

The reliable defence is provenance, not phrasing. AI-detection tools are unreliable in
both directions, so do not write to defeat them — write so that every claim has a
traceable origin, which is also what survives review.

**Do**

- Write prose from your own run artifacts and your own lab notes. The numbers in this
  repository are yours; the sentences describing them should be too.
- Quote and cite anything taken from another paper, including a definition or a
  metric formulation. Paraphrasing a source without citing it is plagiarism whatever
  produced the paraphrase.
- Build related work from papers you have actually read. Never paste a
  model-generated literature summary — generated citations are frequently wrong or
  nonexistent, and a fabricated reference is a retraction risk.
- Keep a provenance note per figure and table: which `run_id`, which command, which
  date. `specs/roadmap.md` Phase 8 makes this a DoD item.
- Run a similarity check (ACM uses iThenticate) before submission and resolve every
  flagged passage.
- Say plainly when a result is negative, underpowered, or superseded. `FINDINGS.md`
  already does this; carry the same tone into the paper.

**Do not**

- Do not present templated benchmark rows as observed data — report the backfill share.
- Do not quote the superseded 2026-08-30 sweep, or the +17.2 % figure, except as the
  thing being retracted.
- Do not reword text to change its detector score. If a passage needs rewriting, it is
  because it is unclear or not yours, and those are the problems to fix.

## 6. Voice

Short sentences. Active voice. Name the mechanism before the number. State the
limitation in the same paragraph as the claim it limits, not in a distant section.
Where the project changed its mind — the rewriter diagnosis in `FINDINGS.md` was
wrong once before it was right — say so; the sequence is evidence that the final
diagnosis was tested rather than assumed.

## 7. Pre-submission checklist

- [ ] Every table caption names its `run_id`.
- [ ] Every number re-derived from the artifact directory, independently of the
      harness that produced it.
- [ ] Every threat in `evaluation-protocol.md` §8 addressed in Section 9.
- [ ] +17.2 % retraction explicit.
- [ ] Negative result in the abstract.
- [x] AI disclosure present and accurate. *(Added 2026-09-29; states the
      assistance as substantial rather than incidental, per §5 of this file.)*
- [ ] Similarity check clean. **Yours to run — iThenticate is licensed and
      cannot be run from here. ACM also runs it at submission.**
- [ ] Artifact appendix points at an archived snapshot with a DOI.
      *(Appendix written 2026-09-29 and deliberately carries no DOI: none has
      been minted, and a citation to a deposit that does not exist is the
      failure this paper argues against. Mint it from a tagged release via
      Zenodo's GitHub integration, deposit the 139 MB snapshot for
      run_1790126271 to the same record, then fill in §A.2.)*
- [ ] Author list, affiliations, and ORCID complete; no AI system as author.
