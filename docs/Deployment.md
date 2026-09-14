# Deployment

**Live:** <https://software-update-questions.streamlit.app/> — public, live APIs,
no API key required.

Deploy target: `app_1.py` (Streamlit Community Cloud).

`marag_app.py` is now a one-line shim that imports `app_1`, so both entrypoints
render the same app. It used to be a second full copy of the pipeline, and
because the Cloud app is configured to serve *that* file, the public URL showed
the older copy: it answered "Any critical Linux updates today?" with a release
whose name was an `HTTPSConnectionPool ... Read timed out` exception, months
after `app_1.py` had been fixed. Two pipelines meant the deployed one was the
one nobody was editing.

If the Streamlit Cloud app setting is repointed to `app_1.py` directly, the
shim can go.

## What the deployed app shows

- **The pipeline, visibly.** Each agent's step, input, output and timing as the
  question runs — the demo doubles as an execution trace.
- **The grounding, visibly.** The question as asked, the question as grounded,
  the phrasings actually fetched, and which results fall inside the resolved
  window.
- **A component monitor.** The sidebar's *Monitor* view watches a comma-separated
  list of components (kept in the URL as `?watch=`): latest shipped version and
  its age, a next-release estimate from the median gap between recent releases,
  advisories in the last 90 days by severity, monthly release/advisory counts,
  version history, and a heuristic risk band that rises with an installed
  version's drift. All of it is derived from `/api/v/search` (see `monitor.py`).
- **The evidence, visibly.** Each claim in the final paragraph carries its
  source in brackets; the sources expand to live release, CVE and community
  links.

## Degradation without a model

Streamlit Community Cloud has no Ollama and holds no API key. Both
model-dependent steps degrade rather than fail, and the UI says which path ran:

| Step | With a model | Without |
|---|---|---|
| Query rewriting | Llama 3.1 rewrite | Rule-based expansion |
| Answer presentation | Model-written cited paragraph | The same shape composed by rule, labelled *rule-based* |
| Temporal grounding | — | Unchanged; it never needed a model |

The labelling matters: rule-based prose is never presented as model output.

## Configuring a presenting model

In `.streamlit/secrets.toml`:

```toml
PRESENTER_MODEL = "openai:gpt-4o-mini"
OPENAI_API_KEY  = "sk-..."
```

or in the environment:

```bash
PRESENTER_MODEL=ollama:llama3.1 streamlit run app_1.py
```

Any spec `eval_harness/providers.py` understands works: `ollama:*`, `openai:*`,
`anthropic:*`. A bare model name defaults to the Ollama backend.

## Pinned dependencies

`requirements.txt` pins versions so a re-run reproduces the reported numbers.
The harness needs only `requests`, `numpy` and `pytest`; `streamlit` is listed
for the demo UI and is deliberately **not** installed in the evaluation
virtualenv, since the UI is not exercised by the harness or the tests.

## A note on latency

Roughly 23 s per question for the multi-agent pipeline against 12 s for the
baseline, on the ground-truth set. The union fetch costs about one additional
set of retrieval calls; the rest is the rewriter's generation call, the
Evaluator's scoring pass, and any retry the Evaluator triggers.
