"""Central configuration for the evaluation harness."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")


@dataclass
class EvalConfig:
    # Which systems to evaluate. See generators.build_generators for the grammar.
    generators: List[str] = field(default_factory=lambda: [
        "marag",
        "single_agent",
        "raw:ollama:llama3.1",
        "raw:ollama:mistral",
    ])
    # Model used for judging (qrels + answer scoring). Keep it distinct from the
    # systems under test to reduce self-evaluation bias.
    judge: str = "ollama:llama3.1"
    # Dataset file (relative to project root) and how many questions to use.
    dataset: str = "validation_gt.json"
    limit: int = 0                      # 0 = all
    # Retrieval / metric settings.
    top_k: int = 4
    ks: List[int] = field(default_factory=lambda: [1, 3, 5])
    seed: int = 42
    # Where to write the run.
    results_dir: str = RESULTS_DIR
