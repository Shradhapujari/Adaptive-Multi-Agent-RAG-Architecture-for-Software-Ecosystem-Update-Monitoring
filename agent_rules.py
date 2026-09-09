"""The rules in AGENT_RULES.md, loaded once and prepended to agent prompts.

Editing the markdown file changes agent behaviour with no code change. A
missing file is not an error: the agents keep their built-in instructions.
"""

from functools import lru_cache
from pathlib import Path

RULES_FILE = Path(__file__).with_name("AGENT_RULES.md")


@lru_cache(maxsize=1)
def rules_block() -> str:
    """The rules as a prompt block, or "" when the file is absent/empty."""
    try:
        text = RULES_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    body = text[text.index("## "):] if "## " in text else text
    return f"# Agent Rules\n\n{body}\n\n---\n\n" if body else ""


if __name__ == "__main__":
    block = rules_block()
    assert block.endswith("---\n\n"), "rules block must end with a separator"
    assert "Grounding" in block, "AGENT_RULES.md lost its Grounding section"
    assert "Edit this file" not in block, "prose before the first ## must be stripped"
    assert rules_block() is block, "rules should be read once, not per call"
    print("ok")
