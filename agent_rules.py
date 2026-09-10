"""The rules in AGENT_RULES.md, loaded once and prepended to agent prompts.

Editing the markdown file changes agent behaviour with no code change. A
missing file is not an error: the agents keep their built-in instructions.

MARAG_RULES=off suppresses the block everywhere it is used. The eval harness
sets that for itself, because its published numbers were produced before this
file existed and every prompt it sends has to stay the prompt that produced
them unless an arm says otherwise. The app sets nothing and gets the rules.
"""

import os
from functools import lru_cache
from pathlib import Path

RULES_FILE = Path(__file__).with_name("AGENT_RULES.md")
RULES_ENV = "MARAG_RULES"


@lru_cache(maxsize=1)
def _file_block() -> str:
    """The file, read once. The switch is checked per call, not cached with it."""
    try:
        text = RULES_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    body = text[text.index("## "):] if "## " in text else text
    return f"# Agent Rules\n\n{body}\n\n---\n\n" if body else ""


def rules_block() -> str:
    """The rules as a prompt block; "" when switched off, absent or empty."""
    if os.environ.get(RULES_ENV, "on").strip().lower() in ("off", "0", "false", "no"):
        return ""
    return _file_block()


if __name__ == "__main__":
    block = rules_block()
    assert block.endswith("---\n\n"), "rules block must end with a separator"
    assert "Grounding" in block, "AGENT_RULES.md lost its Grounding section"
    assert "Edit this file" not in block, "prose before the first ## must be stripped"
    assert rules_block() is block, "rules should be read once, not per call"
    os.environ[RULES_ENV] = "off"
    assert rules_block() == "", "MARAG_RULES=off must suppress the block"
    del os.environ[RULES_ENV]
    assert rules_block() == block, "and unset must bring it back"
    print("ok")
