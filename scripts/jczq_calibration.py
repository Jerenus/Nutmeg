"""Calibration check for JCZQ tiered picks — spec §30.

Replaces single-day rule churn with cumulative calibration. Reads every
``tiered-plan-review.json`` under the daily tree, collects one row per graded
leg ``(implied_prob_from_odds, hit)``, and reports realized hit-rate per
implied-probability bucket / market / tier. A bucket only earns a calibration
verdict once it has ≥ ``MIN_BUCKET_N`` samples; below that it is shown as
``thin`` — the whole point is to NOT change the model on noise.

History (created 2026-05-19 as a stub during §17 sediment; wired to real data
2026-05-30 after the 5/29 backtest where 9 matches drew 5 times and every
"铁胆" 55–59% leg was exposed as ~40% realized).

Usage:
    python scripts/jczq_calibration.py [--daily-dir DIR] [--write PATH]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

DEFAULT_DAILY = ".nutmeg-data/jczq/daily"
DEFAULT_OUT = ".nutmeg-data/jczq/calibration-log.json"

# A probability bucket needs this many graded legs before its realized
# hit-rate is treated as signal rather than noise (spec §30.2).
MIN_BUCKET_N = 30
# Deviation from bucket midpoint that flags miscalibration once n ≥ MIN.
CALIB_TOLERANCE = 0.12

BUCKETS = [(0.0, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]


def collect_legs(daily_dir: str) -> list[dict]:
    """One row per graded leg across all tiered-plan-review.json files."""
    rows: list[dict] = []
    for fp in sorted(glob.glob(f"{daily_dir}/*/tiered-plan-review.json")):
        date = os.path.basename(os.path.dirname(fp))
        try:
            doc = json.load(open(fp))
        except (OSError, json.JSONDecodeError):
            continue
        for tier in doc.get("tiers") or []:
            if not tier:
                continue
            for lg in tier.get("legs") or []:
                hit = lg.get("hit")
                if hit is None:  # pending / not yet graded
                    continue
                odds = lg.get("tc_odds") or lg.get("odds")
                implied = (1.0 / odds) if odds and odds > 1.0 else None
                rows.append({
                    "date": date,
                    "tier": tier.get("code"),
                    "match_no": lg.get("match_no"),
                    "market": lg.get("market"),
                    "pick": lg.get("pick_label"),
                    "odds": odds,
                    "implied": implied,
                    "hit": bool(hit),
                })
    return rows


def _rate(pairs: list[tuple[int, int]]) -> tuple[int, int]:
    hits = sum(h for h, _ in pairs)
    n = sum(n for _, n in pairs)
    return hits, n


def calibration_table(rows: list[dict]) -> list[dict]:
    agg: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        p = r["implied"]
        if p is None:
            continue
        for lo, hi in BUCKETS:
            if lo <= p < hi:
                agg[(lo, hi)][0] += int(r["hit"])
                agg[(lo, hi)][1] += 1
                break
    out = []
    for lo, hi in BUCKETS:
        hits, n = agg[(lo, hi)]
        if n == 0:
            continue
        realized = hits / n
        mid = (lo + hi) / 2
        if n < MIN_BUCKET_N:
            verdict = f"thin(n<{MIN_BUCKET_N})"
        elif realized < mid - CALIB_TOLERANCE:
            verdict = "OVER-CONFIDENT"
        elif realized > mid + CALIB_TOLERANCE:
            verdict = "under-confident"
        else:
            verdict = "ok"
        out.append({"bucket": f"{lo:.2f}-{hi:.2f}", "n": n, "hits": hits,
                    "realized": round(realized, 3), "mid_pred": mid,
                    "verdict": verdict})
    return out


def _group(rows: list[dict], key: str) -> dict[str, tuple[int, int]]:
    g: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        g[r[key]][0] += int(r["hit"])
        g[r[key]][1] += 1
    return {k: (h, n) for k, (h, n) in g.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-dir", default=DEFAULT_DAILY)
    ap.add_argument("--write", default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = collect_legs(args.daily_dir)
    print(f"graded legs: {len(rows)}")

    print("\n# CALIBRATION (implied-prob bucket -> realized hit rate)")
    print(f"{'bucket':>12} | {'n':>3} | {'hits':>4} | {'realized':>8} | "
          f"{'mid':>6} | verdict")
    for row in calibration_table(rows):
        print(f"{row['bucket']:>12} | {row['n']:>3} | {row['hits']:>4} | "
              f"{row['realized']:>7.1%} | {row['mid_pred']:>5.1%} | "
              f"{row['verdict']}")

    print("\n# by market")
    for m, (h, n) in sorted(_group(rows, "market").items()):
        print(f"  {m:>6}: {h}/{n} = {h / n:.1%}")
    print("# by tier")
    for t, (h, n) in sorted(_group(rows, "tier").items()):
        print(f"  {t}: {h}/{n} = {h / n:.1%}")

    if args.write:
        json.dump({"n_legs": len(rows), "legs": rows,
                   "table": calibration_table(rows)},
                  open(args.write, "w"), ensure_ascii=False, indent=1)
        print(f"\nwrote {args.write}")


if __name__ == "__main__":
    main()
