"""
The CLI's `if __name__ == "__main__"` guard must be the last top-level
statement in multiagent_rag_v3.py.

It was not: the guard sat at line 2060 and `auto_mode` was defined at 2070.
Running `python multiagent_rag_v3.py` called `interactive()` from the middle
of the module body, so the loop started before the rest of the file had
executed. Typing `auto` at the prompt raised
`NameError: name 'auto_mode' is not defined` -- the only way to reach the
definition was to exit the loop first, by which point nothing calls it.

Parsing beats importing here: importing the module loads the corpus and
reaches for Ollama.
"""

import ast
from pathlib import Path

import pytest

SOURCES = ["multiagent_rag_v3.py", "DemoMain3.py"]


@pytest.mark.parametrize("name", SOURCES)
def test_main_guard_is_last_toplevel_statement(name):
    path = Path(__file__).resolve().parent.parent / name
    body = ast.parse(path.read_text()).body
    guards = [
        i for i, node in enumerate(body)
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)
    ]
    assert guards, f"{name}: no __main__ guard found"
    trailing = [type(n).__name__ for n in body[guards[-1] + 1:]]
    assert not trailing, (
        f"{name}: {trailing} defined after the __main__ guard -- anything the "
        f"interactive loop calls from there is unbound while it runs"
    )
