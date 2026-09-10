# Running the System

## Requirements

- Python 3.11
- [Ollama](https://ollama.com/download) with `llama3.1` pulled (generation and
  judge) and `nomic-embed-text` (embedding reranker)
- ~16 GB RAM minimum, 24 GB comfortable
- macOS or Linux; Apple Silicon recommended for Metal acceleration

The evaluation harness itself needs only `requests` plus the standard library.
LangChain, smolagents, FAISS and ChromaDB belong to the demo app and the
alternative implementations, not to `eval_harness/`.

```bash
python3.11 -m venv venv311
source venv311/bin/activate
pip install -r requirements.txt
ollama pull llama3.1
ollama pull nomic-embed-text
```

## The demo

```bash
streamlit run app_1.py
```

`app_1.py` is the deploy target. `marag_app.py` is a one-line shim that imports
it, kept because the Streamlit Cloud app is configured to serve that filename.
See [Deployment](Deployment.md) for the hosted version and for what changes when
no model is reachable.

## The CLI

```bash
python multiagent_rag_v3.py     # full pipeline with a printed execution trace
```

## The evaluation harness

```bash
python -m eval_harness.run_eval --dataset validation_gt.json \
    --generators marag,single_agent --judge ollama:llama3.1
```

## Tests

```bash
python -m pytest tests/ -q      # 643 offline tests
```

Offline in the strict sense: clocks, fetch functions and model clients are
injected, so the suite needs neither a network nor a particular date.

---

## Environment variables

| Variable | Values | What it changes |
|---|---|---|
| `MARAG_RERANK` | `none` · `bm25` · `embed` | Which signal ranks retrieved candidates. `none` reproduces the published substring boost and is kept as the ablation arm. `embed` degrades to `bm25` and reports that it did. |
| `MARAG_CORPUS` | `record:<dir>` · `replay:<dir>` | Freeze the live corpus. Record once, replay for every arm; give each ablation its own directory, since a warm replay against a shared snapshot can backfill it. |
| `PRESENTER_MODEL` | e.g. `ollama:llama3.1`, `openai:gpt-4o`, `anthropic:claude-*` | Which model writes the demo's final cited paragraph. Unset means the rule-based path. Also readable from `.streamlit/secrets.toml`. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | Required by those provider backends, including for a stronger independent judge (`--judge openai:gpt-4o`). |

Model specs are `backend:model`; a bare name defaults to the Ollama backend.
`python -m eval_harness.providers` prints which backends are reachable right
now.

## Useful run flags

| Flag | Purpose |
|---|---|
| `--dataset <path>` | Question set (`validation_gt.json`, `data/benchmark_100.json`, `data/benchmark_300.json`) |
| `--generators` | Arms to run, e.g. `marag,single_agent`, `marag:ollama:mistral`, `selfreflective` |
| `--judge <spec>` | Judge model for answer scoring |
| `--benchmark crag` | Deterministic CRAG-style labelling instead of LLM judging |
| `--resume <run_id>` | Continue an interrupted run |
| `--limit N` | Cap the number of questions |

Expect roughly 60 s per question across three arms; the 300-question set is a
multi-hour run.
