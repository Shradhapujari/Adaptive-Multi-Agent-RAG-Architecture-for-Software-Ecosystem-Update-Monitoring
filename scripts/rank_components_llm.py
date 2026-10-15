"""Ask ChatGPT, Gemini, and local Ollama to rank all 30 ecosystem components
by update urgency, from parametric knowledge alone (no CVE feed, no retrieval)
-- the baseline that docs/component_ranking_*.md's live pipeline ranking is
compared against.

Keys: export OPENAI_API_KEY / GEMINI_API_KEY, or put them in .env (gitignored).
Ollama needs no key but must be running locally with the model pulled.

Run: python scripts/rank_components_llm.py
Writes: docs/llm_update_order_comparison_<date>.md
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ask_external_models import load_dotenv  # noqa: E402  (sys.path set above)
from component_stability_ranking import COMPONENTS, rank_components  # noqa: E402
from eval_harness.providers import LLMError, make_client  # noqa: E402

SPECS = ["openai:gpt-4o-mini", "gemini:gemini-2.5-flash", "ollama:llama3.1"]

RANK_PROMPT_TEMPLATE = """Here are {n} software/firmware components from a typical \
update-management ecosystem:

{listing}

From your own knowledge (no external lookup), order ALL {n} by how urgently \
they should be updated, weighing both:
  - security: known CVE history / typical attack surface
  - stability: how often updates to this component break dependents or need \
to be rolled back

Most urgent to update first, least urgent last.

Respond with ONLY a JSON array of all {n} names, copied exactly as given \
above, in that order. No prose, no markdown fences, no explanation."""


def build_prompt(shuffled: list[str]) -> str:
    listing = "\n".join(f"- {c}" for c in shuffled)
    return RANK_PROMPT_TEMPLATE.format(n=len(shuffled), listing=listing)


def parse_ranking(text: str, components: list[str]) -> list[str]:
    """Strict: the response must be a JSON array that is exactly a permutation
    of `components` (case-insensitive). Raises ValueError otherwise -- a
    near-miss is a failed run, not something to coerce into looking valid."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.lower().startswith("json") else text
    parsed = json.loads(text.strip())
    if not isinstance(parsed, list):
        raise ValueError("response is not a JSON array")
    lookup = {c.lower(): c for c in components}
    canonical = []
    for item in parsed:
        key = str(item).strip().lower()
        if key not in lookup:
            raise ValueError(f"unknown component in response: {item!r}")
        canonical.append(lookup[key])
    if len(canonical) != len(components) or set(canonical) != set(components):
        raise ValueError(f"not a full permutation: got {len(canonical)} of {len(components)}")
    return canonical


def spearman_rho(rank_a: dict[str, int], rank_b: dict[str, int], components: list[str]) -> float:
    n = len(components)
    d2 = sum((rank_a[c] - rank_b[c]) ** 2 for c in components)
    return 1 - (6 * d2) / (n * (n**2 - 1))


def kendall_tau(rank_a: dict[str, int], rank_b: dict[str, int], components: list[str]) -> float:
    n = len(components)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = components[i], components[j]
            sign_a = rank_a[ci] - rank_a[cj]
            sign_b = rank_b[ci] - rank_b[cj]
            if sign_a * sign_b > 0:
                concordant += 1
            elif sign_a * sign_b < 0:
                discordant += 1
    return (concordant - discordant) / (n * (n - 1) / 2)


def main() -> None:
    load_dotenv()
    random.seed(2026_10_15)  # one fixed shuffle, same order shown to every model
    shuffled = COMPONENTS.copy()
    random.shuffle(shuffled)
    prompt = build_prompt(shuffled)

    results: dict[str, list[str] | None] = {}
    raw: dict[str, str] = {}
    for spec in SPECS:
        client = make_client(spec)
        if not client.available():
            print(f"--- {spec}: SKIPPED (no key/model, or SDK not installed)")
            results[spec] = None
            continue

        this_prompt, order, last_err = prompt, None, None
        for attempt in range(1, 3):  # one retry: models occasionally emit a
                                      # duplicate/missing item at 30-length lists
            try:
                text = client.generate(this_prompt, max_tokens=2048)
            except LLMError as e:
                last_err = str(e)
                break
            raw[f"{spec} (attempt {attempt})"] = text
            try:
                order = parse_ranking(text, COMPONENTS)
                break
            except (ValueError, json.JSONDecodeError) as e:
                last_err = str(e)
                this_prompt = (f"{prompt}\n\nYour previous answer was invalid: {e}. "
                                "Return exactly 30 unique names, each exactly once.")

        results[spec] = order
        if order is not None:
            tag = " (needed 1 retry)" if "attempt 2" in "".join(k for k in raw if spec in k) else ""
            print(f"--- {spec}: OK ({len(order)} components ranked){tag}")
        else:
            print(f"--- {spec}: FAILED after retry — {last_err}")

    pipeline_ranked = rank_components()
    results["pipeline:releasetrain"] = [c["name"] for c in pipeline_ranked]

    out_path = ROOT / "docs" / f"llm_update_order_comparison_{date.today().isoformat()}.md"
    write_report(out_path, results, raw)
    print(f"\nWrote {out_path}")


def write_report(path: Path, results: dict[str, list[str] | None], raw: dict[str, str]) -> None:
    ranks = {
        spec: {name: i + 1 for i, name in enumerate(order)}
        for spec, order in results.items() if order is not None
    }
    succeeded = list(ranks.keys())

    lines = [
        f"# LLM vs. pipeline update-order ranking — {date.today().isoformat()}",
        "",
        "Each system ranked all 30 components from its own knowledge (ChatGPT, Gemini, "
        "Ollama) or from a live ReleaseTrain pull (pipeline), with no cross-contamination "
        "between them. Prompt and parsing: `scripts/rank_components_llm.py`.",
        "",
    ]
    if len(succeeded) < len(results):
        failed = [s for s in results if s not in succeeded]
        lines += [f"**Not included below (failed/unavailable): {', '.join(failed)}.** "
                  "See raw responses at the bottom.", ""]

    header = "| component | " + " | ".join(succeeded) + " |"
    sep = "|---|" + "---:|" * len(succeeded)
    lines += [header, sep]
    for name in COMPONENTS:
        row = " | ".join(str(ranks[s][name]) for s in succeeded)
        lines.append(f"| {name} | {row} |")

    if len(succeeded) >= 2:
        lines += ["", "## Pairwise rank correlation", "",
                   "| pair | Spearman's ρ | Kendall's τ |", "|---|---:|---:|"]
        for i in range(len(succeeded)):
            for j in range(i + 1, len(succeeded)):
                a, b = succeeded[i], succeeded[j]
                rho = spearman_rho(ranks[a], ranks[b], COMPONENTS)
                tau = kendall_tau(ranks[a], ranks[b], COMPONENTS)
                lines.append(f"| {a} vs {b} | {rho:.3f} | {tau:.3f} |")

    lines += ["", "## Raw responses (unparsed)", ""]
    for spec, text in raw.items():
        lines += [f"### {spec}", "```", text, "```", ""]

    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
