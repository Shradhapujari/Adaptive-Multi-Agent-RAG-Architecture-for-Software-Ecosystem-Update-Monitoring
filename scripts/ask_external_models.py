"""Ask the hosted models the same question the local arms were asked.

Fills the ChatGPT and Gemini rows of docs/system_comparison_*.md. The ollama and
pipeline rows come from app_1.py's "Run Both & Compare", not from here.

Keys: export them, or put them in .env (gitignored) as KEY=value lines.

Run: python scripts/ask_external_models.py ["question"]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval_harness.providers import LLMError, make_client

QUESTION = "Is it safe to update Firefox right now?"
SPECS = ["openai:gpt-4o-mini", "gemini:gemini-2.5-flash"]


def load_dotenv() -> None:
    """KEY=value lines from .env, without taking a python-dotenv dependency.
    Existing environment wins, so an exported key is not overwritten."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> None:
    load_dotenv()
    question = sys.argv[1] if len(sys.argv) > 1 else QUESTION
    print(f"Q: {question}\n")

    for spec in SPECS:
        client = make_client(spec)
        if not client.available():
            print(f"--- {spec}: SKIPPED (no key, or SDK not installed)\n")
            continue
        start = time.monotonic()
        try:
            answer = client.generate(question)
        except LLMError as e:
            print(f"--- {spec}: FAILED — {e}\n")
            continue
        print(f"--- {spec}  ({time.monotonic() - start:.1f}s)\n{answer}\n")


if __name__ == "__main__":
    main()
