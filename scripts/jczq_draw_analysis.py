"""Cross-day analysis for the '软热规避 / 逆向选平' hypothesis.

Scans every tiered-plan-review.json `results` block. For each match:
  - result_had (胜/平/负) + had_odds (the odds OF the actual result)
Computes: draw rate, and a favourite-proxy hit rate (a低赔 favourite 'won
straight' iff actual is 胜/负 AND that result's odds < 2.0 — i.e. it was the
priced favourite that came in).

This is the数据锚 for: in 软热-clustered books, does following每个正路热门
underperform vs selectively逆向选平?
"""
import json, glob, os
from collections import defaultdict

DAILY = "/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq/daily"
files = sorted(glob.glob(f"{DAILY}/*/tiered-plan-review.json"))

tot = draws = fav_win = fav_seen = 0
per_day = []
soft_hot_outcomes = []  # favourites in 1.45-2.05 band

for fp in files:
    date = os.path.basename(os.path.dirname(fp))
    try:
        d = json.load(open(fp))
    except Exception:
        continue
    res = d.get("results") or {}
    dd_tot = dd_draw = 0
    for mno, r in res.items():
        had = r.get("had")
        if had not in ("胜", "平", "负"):
            continue  # unplayed/blank
        try:
            o = float(r.get("had_odds") or 0)
        except ValueError:
            o = 0.0
        tot += 1; dd_tot += 1
        if had == "平":
            draws += 1; dd_draw += 1
        # favourite-proxy: actual is a side result priced as favourite
        if had in ("胜", "负") and 0 < o < 2.0:
            fav_win += 1
    per_day.append((date, dd_draw, dd_tot))

print(f"# CROSS-DAY OUTCOME BASE RATES ({len(files)} review files)")
print(f"total played matches: {tot}")
print(f"draws: {draws} = {draws/tot:.1%}  (vs ~25-28% league baseline)")
print(f"favourite-side won straight (result odds<2.0): {fav_win} = {fav_win/tot:.1%}")
print(f"=> non-favourite-straight (draw OR upset): {(tot-fav_win)/tot:.1%}")
print("\n# per-day draw count")
for date, dr, t in per_day:
    bar = "■"*dr
    print(f"  {date}: {dr}/{t} draws {bar}")
