# AMARA Evaluation Report

- Dataset: `validation_gt.json` (10 questions, hash `237950e265eb`)
- Judge: `ollama:llama3.1` (active)
- Systems: amara, single_agent, raw:ollama:llama3.1, raw:ollama:mistral
- Seed: 42  |  top_k: 4

Values are mean ± 95% CI. IR metrics use LLM-judged graded relevance (qrels). Answer metrics are LLM-as-judge (0–1).

## Head-to-head

| System | mrr | ndcg@1 | recall@1 | ndcg@3 | recall@3 | ndcg@5 | recall@5 | faithfulness | answer_relevance | correctness | self_quality | latency_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| amara | 0.433±0.272 | 0.167±0.201 | 0.158±0.199 | 0.193±0.186 | 0.275±0.195 | 0.201±0.185 | 0.308±0.209 | 0.660±0.080 | 0.950±0.098 | 0.537±0.152 | 0.535 | 13.83 |
| single_agent | 0.800±0.261 | 0.800±0.261 | 0.425±0.216 | 0.743±0.250 | 0.633±0.261 | 0.744±0.250 | 0.658±0.261 | 0.805±0.093 | 1.000±0.000 | 0.500±0.000 | — | 12.21 |
| raw:ollama:llama3.1 | — | — | — | — | — | — | — | 0.640±0.128 | 1.000±0.000 | 0.417±0.163 | — | 2.19 |
| raw:ollama:mistral | — | — | — | — | — | — | — | 0.600±0.000 | 0.990±0.020 | 0.471±0.036 | — | 1.97 |

## Per-category ndcg@1

| Category | amara | single_agent | raw:ollama:llama3.1 | raw:ollama:mistral |
|---|---|---|---|---|
| Fedora | 0.000±0.000 | 0.000±0.000 | — | — |
| Ubiquiti | 0.333±0.000 | 1.000±0.000 | — | — |
| applehelp | 0.000±0.000 | 1.000±0.000 | — | — |
| comfyui | 0.111±0.218 | 1.000±0.000 | — | — |
| homeassistant | 0.000±0.000 | 1.000±0.000 | — | — |
| linuxquestions | 0.000±0.000 | 0.000±0.000 | — | — |
| openclaw | 0.500±0.980 | 1.000±0.000 | — | — |

> Note: `self_quality` is AMARA's original built-in heuristic, shown only for reference — it is not a standard metric.
