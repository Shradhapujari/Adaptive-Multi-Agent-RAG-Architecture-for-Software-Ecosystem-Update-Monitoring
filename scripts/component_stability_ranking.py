"""Rank 30 ecosystem components by update order (least stable first).

Two independent scores per component, both from live releasetrain.io data:
  - `risk`      : this project's heuristic (monitor.risk), from per-component
                  /api/v/search rows -- severity-weighted advisories + drift.
  - `stability` : releasetrain.io's own score (0-1, higher = more stable), read
                  off the most recent /api/v/search row that carries one.

Sort key is our risk score, descending -- highest risk needs updating soonest.
stability is reported alongside as an external check, not blended in: the two
scores weight CVEs/advisories vs. community sentiment differently and nothing
here has validated that a merged score is better than either alone.

Checked 2026-10-14: stability comes from the search rows, NOT from
/api/v/by-stability. That endpoint returns 100 rows covering 8 products
regardless of `limit` (limit=2000 still yields 100), so 29 of these 30
components never appear in it, and name-matching into it produced one false
hit (macos 0.15, against an actual 0.84). The search rows already carry the
field, so the join was dead weight and has been removed.

Run: python scripts/component_stability_ranking.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import monitor

RELEASES_API = "https://releasetrain.io/api/v/"

# One representative search term per component. Drawn from
# build_multiecosystem_benchmark.ECOSYSTEMS' release_terms, plus brave/opera/
# safari/edge called out explicitly as the browsers under test.
COMPONENTS = [
    "ios", "macos", "safari", "android", "windows", "edge",
    "ubuntu", "debian", "fedora", "arch", "linux",
    "firefox", "chrome", "brave", "opera",
    "docker", "kubernetes", "node", "python", "rust",
    "home assistant", "nextcloud", "wordpress",
    "postgresql", "mysql", "mongodb",
    "git", "grafana", "neovim", "gitlab",
]


def fetch_component_rows(name: str) -> list:
    """Checked 2026-10-14: /api/v/search?q=<name> returns rows for exactly one
    product (q=linux -> 132 advisories, all versionProductName "linux"), so no
    product filter is needed here."""
    r = requests.get(RELEASES_API + "search", params={"q": name, "limit": 300}, timeout=30)
    r.raise_for_status()
    return (r.json() or {}).get("data") or []


def uncapped_severity(risk: dict) -> int:
    """monitor.risk caps its score at 100, which ties 14 of 30 components and
    leaves the urgent half unordered. Same severity weights, no cap, used only
    to break those ties."""
    return sum(monitor.SEVERITY_WEIGHT.get(sev, 3) * n for sev, n in risk["severity"].items())


def latest_stability(rows: list) -> tuple[float | None, int]:
    """(stability of the newest scored row, how many rows carried one).

    The count is the honesty signal: the field is sparse, so chrome's 0.90
    rests on 287 of 300 rows while wordpress's 0.89 rests on 1 of 300 and may
    be far older than the release it sits next to.
    """
    scored = sorted((r for r in rows if r.get("stability") is not None),
                    key=lambda r: r.get("versionReleaseDate", ""), reverse=True)
    return (scored[0]["stability"] if scored else None), len(scored)


def rank_components() -> list[dict]:
    """Live-pull every component's risk/stability and sort by update order
    (highest risk first). Shared by main() and by scripts that need our
    pipeline's ranking alongside an LLM's, e.g. rank_components_llm.py."""
    ranked = []
    for name in COMPONENTS:
        rows = fetch_component_rows(name)
        summary = monitor.summarize(name, rows, days=90)
        stability, n_scored = latest_stability(rows)
        ranked.append({
            "name": name,
            "risk_score": summary["risk"]["score"],
            "severity_raw": uncapped_severity(summary["risk"]),
            "risk_band": summary["risk"]["band"],
            "recent_advisories": summary["risk"]["recent_advisories"],
            "latest_version": summary["latest"]["versionNumber"] if summary["latest"] else None,
            "days_ago": summary["days_ago"],
            "stability": stability,
            "n_scored": n_scored,
            "n_rows": summary["n_rows"],
        })

    ranked.sort(key=lambda c: (c["risk_score"], c["severity_raw"]), reverse=True)
    return ranked


def main() -> None:
    ranked = rank_components()

    print(f"Ranked {len(ranked)} components by update order, {date.today().isoformat()}. "
          f"Higher risk = update sooner. `sev` breaks ties at the capped score of 100.\n")
    print("| # | component | risk | sev | band | advisories (90d) | latest | age (d) | stability | scored rows |")
    print("|---:|---|---:|---:|---|---:|---|---:|---:|---:|")
    for i, c in enumerate(ranked, 1):
        st = f"{c['stability']:.2f}" if c["stability"] is not None else "n/a"
        flag = " ⚠ no data" if c["n_rows"] == 0 else ""
        print(f"| {i} | {c['name']}{flag} | {c['risk_score']} | {c['severity_raw']} | {c['risk_band']} | "
              f"{c['recent_advisories']} | {c['latest_version'] or '—'} | "
              f"{c['days_ago'] if c['days_ago'] is not None else '—'} | {st} | "
              f"{c['n_scored']}/{c['n_rows']} |")

    blind = [c["name"] for c in ranked if c["n_rows"] == 0]
    if blind:
        print(f"\n⚠ No rows returned for: {', '.join(blind)}. Their score of 0 and band "
              f"of 'Low' mean the feed knows nothing about them, NOT that they are safe "
              f"to defer. Read them as unranked.")


if __name__ == "__main__":
    main()
