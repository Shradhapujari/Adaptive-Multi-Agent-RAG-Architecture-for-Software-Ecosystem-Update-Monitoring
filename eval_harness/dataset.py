"""
Dataset loading + freezing.
===========================
Normalizes the project's various question files into a single record shape and
freezes a snapshot (with a content hash) so a run is reproducible even though
the underlying questions come from heterogeneous files.

Record shape:
    {"id", "query", "category", "ground_truth"|None, "reddit_id"|None}

Supported inputs:
  - validation_gt.json     : [{id, sub, title, url, gt}]            -> gt is ground truth
  - table_50_questions.json: [{id, query, category, ...}]           -> no ground truth
  - generic list of {query/question, category?, answer?/gt?}
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional

from .config import ROOT


def _norm_record(raw: dict, idx: int) -> Optional[dict]:
    query = raw.get("query") or raw.get("question") or raw.get("title")
    if not query:
        return None
    gt = raw.get("ground_truth")
    if gt is None:
        gt = raw.get("gt")  # validation_gt.json
    # Treat empty / whitespace ground truth as missing.
    if isinstance(gt, str) and not gt.strip():
        gt = None
    return {
        "id": raw.get("id", idx),
        "query": query.strip(),
        "category": raw.get("category", raw.get("sub", "general")),
        "ground_truth": gt,
        "reddit_id": raw.get("reddit_id") or raw.get("url"),
    }


def load_dataset(path: str, limit: int = 0) -> List[dict]:
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    with open(full, "r") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # try common containers
        for key in ("questions", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ValueError(f"{path}: could not find a question list in dict")
    records = []
    for i, raw in enumerate(data, 1):
        if isinstance(raw, str):
            raw = {"query": raw}
        rec = _norm_record(raw, i)
        if rec:
            records.append(rec)
    if limit and limit > 0:
        records = records[:limit]
    return records


def dataset_hash(records: List[dict]) -> str:
    payload = json.dumps([r["query"] for r in records], sort_keys=True).encode()
    return hashlib.sha1(payload).hexdigest()[:12]
