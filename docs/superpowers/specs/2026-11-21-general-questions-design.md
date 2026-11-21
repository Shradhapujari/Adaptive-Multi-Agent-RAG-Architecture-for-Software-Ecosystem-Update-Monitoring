# General software questions — design (short)

## Intent
The console should answer software questions that aren't about updates:
"Is zoom better or teams?", "What Microsoft outages were there?", "What happened
to Microsoft recently?". Today a question that names a product but matches no
known type gets an act/hold update verdict built from unrelated advisories, so
the result is a confident answer to a question nobody asked.

## Today (measured 2026-11-21)
| Question | Route today |
|---|---|
| Is zoom better or teams? | products found, no live type (the comparison check misses "better … or") → update verdict |
| What microsoft outages where? | `incident` live type → works (web search on only) |
| What happended to miscrosoft recently? | no product, `vendor.suggest` finds nothing → declined |
| What happened to Microsoft recently? / Any news about Slack? | product, no type → update verdict |

## Approaches
1. **Flip the default (picked).** Questions that don't ask about updates get a
   general web answer with no verdict.
2. Model classifier: an LLM labels the question type. Copes better with odd
   phrasing and typos, but costs an extra model call per question, gives answers
   that vary between runs, and drops the offline, testable routing `intent.py`
   was built for.
3. Model answers from its own knowledge: no sources to cite, and it can't know
   what happened recently. Rejected.

### Refinement found while sizing approach 1
The literal flip ("no update cue and no confident intent → general") reroutes
**145 of the 500 benchmark questions**. That includes real update reports such as
"iOS 26.3 WiFi/RAM issues?" and "Is this a glitch/bug with the new Ubuntu 26.04?",
which would lose their verdict. So the flip fires on a positive general-question
cue, not on the absence of an update cue. Measured on the same 500 questions,
**20** match, and they are mostly general ("Why does Linux not need anti-virus
software?", "How does Upsert work?", "Why is MySQL faster than MariaDB?").
Every one of the five example questions matches.

## Design
All of it lives in `live_sources.py` and the existing answer-only path in `app_1.py`.

1. **Two new live types, both answer-only (no verdict):**
   - `news`: cues such as "what happened", "going on with", "recent(ly)",
     "lately", "news", "this week". Searched with `websearch.search(news=True)`
     over the last month.
   - `general`: a question that opens with "what is/are", "what's", "how does",
     "explain" or "why does/is". Searched with a plain web search.
   - Both fire only when the existing classifier makes no confident call and
     `_UPDATE_CUE` doesn't match. They come last in `kind()`'s precedence, so
     outage, EOL, comparison, compatibility and how-to keep their behaviour.
2. **Comparison:** also catch "X better … or Y" and "or … better".
3. **Typos:** add the products the examples name (microsoft, zoom, teams,
   slack) to `vendor.known_products`, so "miscrosoft" gets "Did you mean
   **Microsoft**?". It stays a suggestion and is never silently substituted,
   per the 2026-11-12 "Nodej.s" decision in `vendor.suggest`.
4. **Web search off:** `news` and `general` join `_NEEDS_LIVE`, so they're declined
   with the "turn on web search" note, as outage questions are today.
5. **Default unchanged:** any question that matches none of these cues still
   gets the update pipeline.

## Non-goals
- Questions that name no product ("What is a race condition?") stay declined.
  Telling a software concept from "how do I bake bread" without a product name
  needs its own rule; that's a later round.
- No model-based classification.
- Eval harness untouched: live types are console-only.

## Check
- One test: the five example questions route as above. Add three update
  questions ("Is it safe to update Chrome?", "iOS 26.3 WiFi/RAM issues?",
  "Latest Node.js version?") that must keep the update path.
- Re-run the 500-question count; it should stay at about 20 rerouted.

## Left to the builder
Exact regex wording, the news time window, and the answer-line wording for the
two new types (reuse `KIND_LABEL`).
