"""
Agentic AI Demo: Think & Plan → Select Tools → Act
====================================================
Based on HuggingFace Agents Course (Unit 1) — Alfred Agent pattern.
Reference: https://huggingface.co/learn/agents-course/en/unit1/what-are-agents
How it works (matching Prof's diagram):
  ┌─────────────────┐
  │   User Request  │  "Which posts have the highest sentiment divergence?"
  └────────┬────────┘
           ↓
  ┌─────────────────────────────┐
  │   Step 1: Think & Plan      │  LLM reasons about the task,
  │   (thought bubble)          │  selects which tools to use
  └────────┬────────────────────┘
           ↓  selects tools
  ┌─────────────────────────────┐
  │   Available Tools           │  get_sentiment_overview()
  │   (laptop / blender icons)  │  get_highest_divergence_posts()
  │                             │  get_sentiment_by_subreddit()
  │                             │  get_defect_vs_usability_sentiment()
  └────────┬────────────────────┘
           ↓
  ┌─────────────────────────────┐
  │   Step 2: Act using Tools   │  Tool executes → Observation returned
  │   (agent → tool → result)   │  Loop back to Think & Plan if needed
  └─────────────────────────────┘
           ↓
      Final Answer (plain English)
Usage:
    python DemoMain3.py
    python DemoMain3.py "Which subreddits are most negative?"
    python DemoMain3.py demo
Requirements:
    pip install langchain-classic langchain-core langchain-ollama ollama python-dotenv
    ollama pull llama3.1
"""
import json
import sys
from pathlib import Path
from langchain_ollama import ChatOllama
# langchain 1.x dropped the legacy ReAct agent (create_react_agent/AgentExecutor)
# that this demo is built on; `langchain-classic` is its maintained home.
from langchain_classic.tools import tool
from langchain_classic.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain_classic.callbacks.base import BaseCallbackHandler
# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
DATA_PATH   = Path(__file__).parent / "data" / "enhanced_automated_sentiment_results.json"
LLM_MODEL   = "llama3.1"   # swap to "mistral" if llama3.1 struggles
TEMPERATURE = 0             # deterministic — best practice for agents
# ─────────────────────────────────────────────────────────────
# HuggingFace-style THINK & PLAN → ACT LOGGER
# Matches the Alfred agent diagram from the course
# ─────────────────────────────────────────────────────────────
class AlfredAgentLogger(BaseCallbackHandler):
    """
    Prints the agent loop in the exact framing from the HuggingFace
    agents course:
        USER REQUEST
             ↓
        STEP 1: THINK & PLAN  (LLM reasons + selects tools)
             ↓
        STEP 2: ACT USING TOOLS  (tool runs → observation)
             ↓
        FINAL ANSWER
    """
    W = 58  # width for borders
    def _bar(self, char="─"):
        print(char * self.W)
    def on_llm_start(self, serialized, prompts, **kwargs):
        print()
        self._bar("─")
        print("  💭  STEP 1: THINK & PLAN")
        print(f"      Model  : {LLM_MODEL}")
        print("      Status : reasoning about the task...")
        self._bar("─")
    def on_agent_action(self, action, **kwargs):
        print()
        print("  🔧  SELECT TOOLS")
        print(f"      Tool chosen : {action.tool}")
        print(f"      Tool input  : {action.tool_input}")
        self._bar("─")
        print()
        print("  ⚡  STEP 2: ACT USING TOOLS")
        print(f"      Calling     : {action.tool}({action.tool_input})")
        self._bar("─")
    def on_tool_end(self, output, **kwargs):
        try:
            parsed  = json.loads(output)
            preview = json.dumps(parsed, indent=2)
            if len(preview) > 500:
                preview = preview[:500] + "\n      ... (truncated)"
        except Exception:
            preview = str(output)[:500]
        print()
        print("  👁  OBSERVATION (tool result):")
        for line in preview.split("\n"):
            print(f"      {line}")
    def on_agent_finish(self, finish, **kwargs):
        print()
        self._bar("═")
        print("  ✅  FINAL ANSWER")
        self._bar("═")
        answer = finish.return_values.get("output", "No answer returned.")
        for line in answer.split("\n"):
            print(f"  {line}")
        self._bar("═")
    def on_chain_error(self, error, **kwargs):
        print(f"\n  ❌  ERROR: {error}")
# ─────────────────────────────────────────────────────────────
# DATA LOADER
# ─────────────────────────────────────────────────────────────
def _load_data() -> dict:
    if not DATA_PATH.exists():
        print(f"\n⚠️  Dataset not found at: {DATA_PATH}")
        print("    → Copy enhanced_automated_sentiment_results.json into ./data/")
        return {}
    with open(DATA_PATH) as f:
        data = json.load(f)
    print(f"✅  Dataset loaded: {len(data.get('all_analyzed_posts', []))} posts")
    return data
_SENTIMENT_DATA = _load_data()
_ALL_POSTS: list[dict] = _SENTIMENT_DATA.get("all_analyzed_posts", [])
# ─────────────────────────────────────────────────────────────
# TOOLS  (the "laptop / blender" layer in the diagram)
# Best practice: one tool per domain, returns structured JSON
# ─────────────────────────────────────────────────────────────
@tool
def get_sentiment_overview() -> str:
    """
    Returns a high-level overview of the Reddit sentiment dataset:
    total posts analyzed, sentiment model used, and quality filtering criteria.
    Use this for general questions about the dataset.
    """
    if not _SENTIMENT_DATA:
        return json.dumps({"error": "Dataset not loaded"})
    meta = _SENTIMENT_DATA.get("analysis_metadata", {})
    return json.dumps({
        "total_posts_fetched":  meta.get("total_posts_fetched"),
        "total_posts_analyzed": meta.get("total_posts_analyzed"),
        "sentiment_model":      meta.get("sentiment_model"),
        "analysis_date":        meta.get("date"),
        "filtering_criteria":   meta.get("enhanced_filtering"),
    }, indent=2)
@tool
def get_highest_divergence_posts() -> str:
    """
    Returns the top N Reddit posts with the highest author-community
    sentiment divergence. Divergence measures how differently the
    original poster and the community responded to the same thread.
    High divergence = frustrated author, supportive community (or vice versa).
    Use for questions about author vs community sentiment gaps.
    Args:
        top_n: number of posts to return (default 5, max 10)
    """
    if not _ALL_POSTS:
        return json.dumps({"error": "Dataset not loaded"})
    top_n = 5
    ranked = sorted(
        _ALL_POSTS,
        key=lambda p: p.get("metrics", {}).get("sentiment_divergence", 0),
        reverse=True
    )[:top_n]
    return json.dumps([{
        "rank":                    i + 1,
        "title":                   p.get("title"),
        "subreddit":               f"r/{p.get('subreddit')}",
        "sentiment_divergence":    round(p["metrics"].get("sentiment_divergence", 0), 3),
        "author_avg_sentiment":    round(p["metrics"].get("author_avg_sentiment", 0), 3),
        "community_avg_sentiment": round(p["metrics"].get("community_avg_sentiment", 0), 3),
        "interpretation": (
            "author more negative than community"
            if p["metrics"].get("author_avg_sentiment", 0) < p["metrics"].get("community_avg_sentiment", 0)
            else "author more positive than community"
        ),
        "url": p.get("url"),
    } for i, p in enumerate(ranked)], indent=2)
@tool
def get_sentiment_by_subreddit() -> str:
    """
    Groups all posts by subreddit and returns the average community
    sentiment score per subreddit, sorted from most negative to most positive.
    Use for questions about which communities react most negatively or positively
    to software updates.
    """
    if not _ALL_POSTS:
        return json.dumps({"error": "Dataset not loaded"})
    stats: dict[str, list[float]] = {}
    for post in _ALL_POSTS:
        sub   = post.get("subreddit", "unknown")
        score = post.get("metrics", {}).get("community_avg_sentiment", 0)
        stats.setdefault(sub, []).append(score)
    result = sorted([{
        "subreddit":               f"r/{sub}",
        "avg_community_sentiment": round(sum(s) / len(s), 3),
        "post_count":              len(s),
        "sentiment_label": (
            "positive" if sum(s)/len(s) >= 0.05
            else "negative" if sum(s)/len(s) <= -0.05
            else "neutral"
        ),
    } for sub, s in stats.items()], key=lambda x: x["avg_community_sentiment"])
    return json.dumps(result, indent=2)
@tool
def get_defect_vs_usability_sentiment() -> str:
    """
    Compares average sentiment metrics between two post categories:
    - Software defect posts (bug reports, crashes, errors)
    - Usability/release posts (updates, new features, improvements)
    Returns avg author sentiment, community sentiment, and divergence per category.
    Use for questions about how sentiment differs between defect and usability topics.
    """
    if not _ALL_POSTS:
        return json.dumps({"error": "Dataset not loaded"})
    defect_kw    = ["fix","bug","error","issue","broken","crash","fail","defect","problem"]
    usability_kw = ["update","new","release","feature","improve","upgrade","version","launch"]
    defect, usability = [], []
    for post in _ALL_POSTS:
        title = post.get("title", "").lower()
        m     = post.get("metrics", {})
        entry = {
            "author":    m.get("author_avg_sentiment", 0),
            "community": m.get("community_avg_sentiment", 0),
            "div":       m.get("sentiment_divergence", 0),
        }
        if any(kw in title for kw in defect_kw):    defect.append(entry)
        if any(kw in title for kw in usability_kw): usability.append(entry)
    def avg(posts, label):
        if not posts:
            return {"category": label, "post_count": 0}
        n = len(posts)
        return {
            "category":                label,
            "post_count":              n,
            "avg_author_sentiment":    round(sum(p["author"]    for p in posts) / n, 3),
            "avg_community_sentiment": round(sum(p["community"] for p in posts) / n, 3),
            "avg_divergence":          round(sum(p["div"]       for p in posts) / n, 3),
        }
    return json.dumps({
        "results": [
            avg(defect,    "software_defect"),
            avg(usability, "usability_release"),
        ],
        "interpretation": {
            "divergence":         "higher = author and community reacted differently",
            "negative_author":    "author was frustrated or critical",
            "positive_community": "community was helpful or supportive",
        }
    }, indent=2)
@tool
def get_post_by_id(post_id: str) -> str:
    """
    Returns full sentiment details for a single Reddit post by its ID.
    Use when drilling into a specific post mentioned in a previous result.
    Args:
        post_id: Reddit post ID string (e.g. '1o094i5')
    """
    if not _ALL_POSTS:
        return json.dumps({"error": "Dataset not loaded"})
    for post in _ALL_POSTS:
        if post.get("post_id") == post_id:
            return json.dumps({
                "post_id":         post.get("post_id"),
                "title":           post.get("title"),
                "subreddit":       f"r/{post.get('subreddit')}",
                "url":             post.get("url"),
                "score":           post.get("score"),
                "num_comments":    post.get("num_comments"),
                "title_sentiment": post.get("title_sentiment"),
                "metrics":         post.get("metrics"),
            }, indent=2)
    return json.dumps({"error": f"Post '{post_id}' not found"})
# ─────────────────────────────────────────────────────────────
# TOOL REGISTRY
# ─────────────────────────────────────────────────────────────
TOOLS = [
    get_sentiment_overview,
    get_highest_divergence_posts,
    get_sentiment_by_subreddit,
    get_defect_vs_usability_sentiment,
    get_post_by_id,
]
# ─────────────────────────────────────────────────────────────
# REACT PROMPT
# ─────────────────────────────────────────────────────────────
REACT_PROMPT = PromptTemplate.from_template("""
You are an intelligent agent (like Alfred from the HuggingFace agents course).
Your job: receive a user request, think and plan which tools to use, then act.
Dataset context: {total_posts} Reddit posts about software updates, analyzed
using VADER sentiment analysis. Each post has author sentiment trajectory,
community sentiment trajectory, and a divergence score.
STEP 1 — THINK & PLAN:
  Read the user request carefully.
  Decide which tool(s) will best answer it.
  Think about what the result will tell you.
STEP 2 — ACT USING TOOLS:
  Call the selected tool.
  Use the observation to build your answer.
  Repeat if you need more information.
Available tools:
{tools}
Tool names: {tool_names}
Required format:
Question: the user's request
Thought: think and plan — what does this question need? which tool fits?
Action: tool name (must be one of [{tool_names}])
Action Input: input for the tool
Observation: result from the tool
... (repeat Thought/Action/Action Input/Observation if needed)
Thought: I now have enough to answer
Final Answer: clear, plain English answer based on the data
Begin!
Question: {input}
Thought:{agent_scratchpad}
""")
# ─────────────────────────────────────────────────────────────
# AGENT SETUP
# ─────────────────────────────────────────────────────────────
llm = ChatOllama(model=LLM_MODEL, temperature=TEMPERATURE)
agent = create_react_agent(
    llm=llm,
    tools=TOOLS,
    prompt=REACT_PROMPT.partial(total_posts=len(_ALL_POSTS)),
)
agent_executor = AgentExecutor(
    agent=agent,
    tools=TOOLS,
    verbose=False,
    handle_parsing_errors=True,
    max_iterations=10,
    callbacks=[AlfredAgentLogger()],
)
# ─────────────────────────────────────────────────────────────
# DEMO QUERIES
# ─────────────────────────────────────────────────────────────
DEMO_QUERIES = [
    "Which posts have the highest author-community sentiment divergence?",
    "Summarize sentiment trends for software defect posts",
    "What subreddits show the most negative community reaction?",
]
# ─────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────
def run_query(question: str):
    W = 58
    print(f"\n{'═' * W}")
    print(f"  📨  USER REQUEST")
    print(f"{'─' * W}")
    print(f"  {question}")
    print(f"{'═' * W}")
    try:
        agent_executor.invoke({"input": question})
    except Exception as e:
        print(f"  ❌  Agent error: {e}")
        print(f"  💡  Tip: try LLM_MODEL = 'mistral' if llama3.1 is struggling")
def run_interactive():
    W = 58
    print(f"\n{'═' * W}")
    print("  🤖  Alfred Agent  —  releasetrain.io Sentiment")
    print(f"  📊  Dataset  : {len(_ALL_POSTS)} posts  |  47 subreddits")
    print(f"  🧠  Model    : {LLM_MODEL} via Ollama (local)")
    print(f"  🔧  Tools    : {len(TOOLS)} available")
    print(f"  🔁  Pattern  : Think & Plan → Select Tools → Act")
    print(f"{'─' * W}")
    print("  Available tools:")
    for t in TOOLS:
        print(f"    • {t.name}")
    print(f"{'─' * W}")
    print("  Commands: 'demo' | 'tools' | 'exit' | any question")
    print(f"{'═' * W}")
    while True:
        try:
            user_input = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        if user_input.lower() == "demo":
            for q in DEMO_QUERIES:
                run_query(q)
        elif user_input.lower() == "tools":
            print("\nAvailable tools:")
            for t in TOOLS:
                print(f"  • {t.name}: {t.description.split(chr(10))[0]}")
        else:
            run_query(user_input)
# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = " ".join(sys.argv[1:])
        if arg.lower() == "demo":
            for q in DEMO_QUERIES:
                run_query(q)
        else:
            run_query(arg)
    else:
        run_interactive()
