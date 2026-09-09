"""
Pick the model for a role, and say why that one.

Two constraints the project already lives under, in one place instead of three:

1. Whatever is configured may not be there. The deployed Streamlit host has no
   Ollama and may hold no key, so a hard-coded spec is a demo that dies on the
   machine it is demoed from. Selection probes first and falls back.
2. The judge may not share a model family with a system under test (threat T2
   in evaluation-protocol.md). llama3.1 judging a llama3.1 generator is not an
   evaluation, and that mistake is invisible in the output.

The registry is deliberately a literal table. Costs are per 1k output tokens,
list price at the time of writing, and only decide ties -- they are here to
prefer the local model, not to be a billing model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

__all__ = ["MODELS", "Choice", "select", "available"]

# quality: 1 small/local, 2 mid, 3 frontier. Roles ask for a floor.
MODELS = (
    {"spec": "ollama:llama3.1",         "family": "llama",  "quality": 1, "usd_per_1k": 0.0},
    {"spec": "ollama:mistral",          "family": "mistral","quality": 1, "usd_per_1k": 0.0},
    {"spec": "openai:gpt-4o-mini",      "family": "gpt",    "quality": 2, "usd_per_1k": 0.0006},
    {"spec": "openai:gpt-4o",           "family": "gpt",    "quality": 3, "usd_per_1k": 0.010},
    {"spec": "anthropic:claude-sonnet-5","family": "claude","quality": 3, "usd_per_1k": 0.015},
)

# The floor each role needs. Presenting is a summarisation of text already in
# the prompt, which a local 8B does; judging is the measurement instrument.
ROLE_MIN_QUALITY = {"present": 1, "judge": 2}


@dataclass
class Choice:
    spec: Optional[str]
    reason: str
    considered: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.spec is not None


def available(spec: str) -> bool:
    """Is this spec actually reachable right now? (network / key check)"""
    try:
        from eval_harness.providers import make_client
        return make_client(spec).available()
    except Exception:      # noqa: BLE001 — an unimportable backend is unavailable
        return False


def select(role: str = "present", exclude_families: Sequence[str] = (),
           probe: Optional[Callable[[str], bool]] = None) -> Choice:
    """Cheapest reachable model that clears the role's quality floor.

    `exclude_families` is how judge independence is enforced: pass the family
    of every system under test.
    """
    if role not in ROLE_MIN_QUALITY:
        raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLE_MIN_QUALITY)}")
    probe = probe or available
    floor = ROLE_MIN_QUALITY[role]
    banned = {f.lower() for f in exclude_families}

    eligible = [m for m in MODELS if m["quality"] >= floor and m["family"] not in banned]
    considered = [m["spec"] for m in eligible]
    for m in sorted(eligible, key=lambda m: (m["usd_per_1k"], -m["quality"])):
        if probe(m["spec"]):
            cost = "free, local" if not m["usd_per_1k"] else f"${m['usd_per_1k']}/1k out"
            why = f"cheapest reachable at quality>={floor} for {role} ({cost})"
            if banned:
                why += f"; excluded {', '.join(sorted(banned))}"
            return Choice(m["spec"], why, considered)

    return Choice(None, f"nothing reachable for {role} "
                        f"(quality>={floor}, excluded {sorted(banned) or 'nothing'})",
                  considered)


def _demo() -> None:
    only = lambda *ok: (lambda spec: spec in ok)          # noqa: E731 — stub prober

    c = select("present", probe=only("ollama:llama3.1", "openai:gpt-4o"))
    assert c.spec == "ollama:llama3.1", c                  # free beats better

    c = select("judge", probe=only("ollama:llama3.1", "openai:gpt-4o-mini", "openai:gpt-4o"))
    assert c.spec == "openai:gpt-4o-mini", c               # local is below the judge floor

    # A llama generator under test cannot be judged by a llama judge; here the
    # exclusion does nothing because the floor already ruled it out, so exclude
    # the family that would otherwise win.
    c = select("judge", exclude_families=["gpt"],
               probe=only("openai:gpt-4o-mini", "anthropic:claude-sonnet-5"))
    assert c.spec == "anthropic:claude-sonnet-5", c
    assert "openai:gpt-4o-mini" not in c.considered

    c = select("judge", probe=only("ollama:mistral"))
    assert not c and c.spec is None, c                     # falls through, does not guess
    try:
        select("rerank")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown role should raise")

    for role in ROLE_MIN_QUALITY:                          # live, on this machine
        live = select(role)
        print(f"{role:8s} -> {live.spec or 'none'}  ({live.reason})")


if __name__ == "__main__":
    _demo()
