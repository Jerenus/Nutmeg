#!/usr/bin/env python
"""Parse the prose tallies in `.nutmeg-data/scoreboard.json` into structured counters.

The scoreboard is the single source of truth for rule-chain 战绩, but each chain's
`tally` is a Chinese prose string such as ``⛔证伪 (291条决策/18期, R_excl=-2.3pp, CI含0)``
or ``3/6未赢;持平开平分型2/2→3/6已退休``. Replay experiments cannot compare against
that. This module extracts what is machine-readable and leaves the rest ``None``:

    n, issues, hits/total (first ``a/b`` fragment), R_pp, ci (lo, hi) or ci_contains_zero,
    mde80_pp, verdict (证伪/确认/退休/...), status (copied), plus the raw text.

It never edits the scoreboard. ``uv run python experiments/scoreboard_parse.py`` prints
the table and a coverage line; ``--out <path>`` writes the JSON.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOREBOARD = ROOT / ".nutmeg-data" / "scoreboard.json"

_RE_N = re.compile(r"(?<![\d/])n\s*=\s*(\d+)")
_RE_DECISIONS = re.compile(r"(\d+)\s*条决策")
_RE_ISSUES = re.compile(r"(\d+)\s*期")
_RE_FRACTION = re.compile(r"(?<![\d.])(\d+)\s*/\s*(\d+)(?![\d.%])")
_RE_R = re.compile(r"R(?:_[a-z]+)?\s*=\s*([+-]?\d+(?:\.\d+)?)\s*pp")
_RE_CI = re.compile(r"CI\s*\[\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\]")
_RE_CI_ZERO = re.compile(r"CI\s*含\s*0")
_RE_MDE = re.compile(r"MDE80\s*=\s*([+-]?\d+(?:\.\d+)?)\s*pp")
_RE_CASES = re.compile(r"(\d+)\s*例")
_RE_STREAK = re.compile(r"连续\s*(\d+)\s*期")
_VERDICTS = (
    ("证伪", "falsified"),
    ("反向确认", "confirmed_reverse"),
    ("确认", "confirmed"),
    ("退休", "retired"),
    ("禁用", "disabled"),
    ("欠功效", "underpowered"),
    ("正样本", "positive_sample"),
    ("保守成本", "conservatism_cost"),
)


def parse_tally(text: str) -> dict:
    """Extract structured fields from one tally string; unknown fields stay None."""
    text = text or ""
    out: dict = {
        "n": None,
        "issues": None,
        "hits": None,
        "total": None,
        "R_pp": None,
        "ci": None,
        "ci_contains_zero": None,
        "mde80_pp": None,
        "cases": None,
        "streak_issues": None,
        "verdict": None,
        "raw": text,
    }
    if m := _RE_N.search(text):
        out["n"] = int(m.group(1))
    elif m := _RE_DECISIONS.search(text):
        out["n"] = int(m.group(1))
    if m := _RE_ISSUES.search(text):
        out["issues"] = int(m.group(1))
    for m in _RE_FRACTION.finditer(text):
        hits, total = int(m.group(1)), int(m.group(2))
        # five-digit pairs such as 26127/26128 are issue numbers, not tallies
        if hits <= total < 10000:
            out["hits"], out["total"] = hits, total
            break
    if m := _RE_R.search(text):
        out["R_pp"] = float(m.group(1))
    if m := _RE_CI.search(text):
        lo, hi = float(m.group(1)), float(m.group(2))
        out["ci"] = [lo, hi]
        out["ci_contains_zero"] = lo <= 0 <= hi
    elif _RE_CI_ZERO.search(text):
        out["ci_contains_zero"] = True
    if m := _RE_MDE.search(text):
        out["mde80_pp"] = float(m.group(1))
    if m := _RE_CASES.search(text):
        out["cases"] = int(m.group(1))
    if m := _RE_STREAK.search(text):
        out["streak_issues"] = int(m.group(1))
    for needle, label in _VERDICTS:
        if needle in text:
            out["verdict"] = label
            break
    return out


def parse_scoreboard(document: dict) -> dict:
    chains = document.get("chains") or {}
    parsed = {}
    for name, chain in chains.items():
        chain = chain if isinstance(chain, dict) else {"tally": str(chain)}
        entry = parse_tally(str(chain.get("tally") or ""))
        entry["status"] = chain.get("status")
        entry["machine_readable"] = any(
            entry[k] is not None
            for k in ("n", "hits", "R_pp", "ci", "ci_contains_zero", "cases", "streak_issues")
        )
        parsed[name] = entry
    readable = sum(1 for e in parsed.values() if e["machine_readable"])
    return {
        "source_updated_at": document.get("updated_at"),
        "chains": parsed,
        "coverage": {"chains": len(parsed), "machine_readable": readable},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scoreboard", type=Path, default=SCOREBOARD)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    result = parse_scoreboard(json.loads(args.scoreboard.read_text(encoding="utf-8")))
    for name, entry in result["chains"].items():
        frac = f"{entry['hits']}/{entry['total']}" if entry["total"] is not None else "-"
        print(
            f"{name:<34} status={str(entry['status']):<18} n={str(entry['n']):<5} "
            f"hits={frac:<7} R={str(entry['R_pp']):<6} ci0={str(entry['ci_contains_zero']):<5} "
            f"verdict={entry['verdict']}"
        )
    cov = result["coverage"]
    print(f"machine-readable chains: {cov['machine_readable']}/{cov['chains']}")
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
