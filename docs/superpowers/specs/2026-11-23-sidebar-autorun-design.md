# Sidebar questions run on click — design

**Why.** In the default Decision console, clicking an example query or a Reddit
pick does nothing visible: the sidebar writes `main_query` (the classic view's
box) while the console reads `ask_query` and only runs on its own Ask button.
The console also never passes the picked thread's `reddit_id` to the pipeline,
so a Reddit pick is not answered from its own thread — the original picker's
behaviour (ed4db46) is lost there.

**Goal.** One click on any sidebar question fills the box, runs it, and shows
the answer, in every answering mode. A Reddit pick is answered from that
thread (top-voted comment, yes/no tally).

**Non-goals.** No change to the pipeline, the feed endpoints, or how the
yes/no filter picks questions. Opening the "Pick a Reddit question" expander
does not run anything.

**Anti-goal.** A rerun that re-submits on its own (the run flag must be
consumed once), or a run started without a click (Ollama is one job at a time).

**Approaches.**
- *Chosen:* one `_submit(q, row=None)` helper used as an `on_click` callback by
  every sidebar control; it writes both boxes, sets/clears `reddit_id`, and sets
  a one-shot `auto_ask` flag the console and classic views pop and treat like
  their Ask/Run button.
- *Rejected:* auto-run when the Reddit expander opens — Streamlit has no
  reliable open event, and browsing would start a run.
- *Rejected:* move the sidebar onto the console's key only — leaves the
  classic modes broken the other way.

**Decided.**
- Latest: newest yes/no question on page 1 (vendor-filtered), runs at once.
- Random: question from any page (vendor-filtered, "All" = general), runs at once.
- Question dropdown pick, the eight example queries, and Store's "Ask again" run at once.
- `ask()` takes `reddit_id` and passes it to `run_pipeline`; the picked thread
  only applies while the box still holds its title (same rule as classic view).

**Left to the builder.** How the console shows the thread's top comment, reusing
what the classic view already renders where possible.
