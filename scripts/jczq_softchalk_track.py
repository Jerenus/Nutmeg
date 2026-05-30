"""§31 软热反面 paper-trade 追踪 — 机会识别样本积累器。

为验证 spec §31 的核心假设：**软热（soft chalk）的反面（平/冷）被市场高估
推高了赔率，主动捕捉反面长期回报 > 跟随正路**。每场已结算比赛产出最多一条
样本行：软热的反面 pick + 反面赔率 + 是否命中 + 单位回报（命中=反面赔率−1，
未中=−1）。跨日累积，样本 ≥ MIN_SAMPLES 才看结论（守 §30：不靠单日）。

分类（§31.1，纯 had 三向赔率，无需欧赔依赖以便历史回填）：
  fav_odds = min(home, away);  implied = 1/fav_odds
  硬热  : fav_odds ≤ 1.50            -> 正路（不进本表，本表只追软热反面）
  软热  : 1.50 < fav_odds ≤ 2.10     -> 反面 = 平 或 冷（非最热的另一边），
          方向用赔率结构选更便宜/更可能的一侧（§31.2）
  其它  : fav_odds > 2.10            -> coinflip/开放，无明确热门，跳过

反面方向（§31.2）：
  让 underdog_odds = max(home, away)，draw_odds = 平赔
  若 underdog 一侧 implied（1/odds）≥ 平 implied -> 偏“冷”（押 underdog 方向）
  否则 -> 偏“平”
回报对照实际 had 结果。

数据源：
  - 赛前三向 had 赔率：daily/<date>/context.json -> matches[].candidates
    里 pool=='had' 的三条（pick 胜/平/负 + odds）
  - 实际结果：daily/<date>/tiered-plan-review.json -> results[match_no].had

Usage:
  python scripts/jczq_softchalk_track.py [--daily-dir DIR] [--write PATH]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

DEFAULT_DAILY = ".nutmeg-data/jczq/daily"
DEFAULT_OUT = ".nutmeg-data/jczq/softchalk-track.json"

SOFT_LO = 1.50   # exclusive lower (≤1.50 = 硬热)
SOFT_HI = 2.10   # inclusive upper (>2.10 = coinflip/开放)
MIN_SAMPLES = 30  # §30 纪律：样本够了才下结论


def _prematch_had(daily_dir: str, date: str) -> dict[str, dict[str, float]]:
    """match_no -> {'胜':odds,'平':odds,'负':odds} from context candidates."""
    fp = f"{daily_dir}/{date}/context.json"
    out: dict[str, dict[str, float]] = {}
    try:
        ctx = json.load(open(fp))
    except (OSError, json.JSONDecodeError):
        return out
    for m in ctx.get("matches") or []:
        mno = m.get("match_no")
        had: dict[str, float] = {}
        for c in m.get("candidates") or []:
            if c.get("pool") != "had":
                continue
            pick = c.get("pick")
            odds = c.get("odds")
            if pick in ("胜", "平", "负") and odds and odds > 1.0:
                # keep the first (or lowest) odds seen per pick
                if pick not in had or odds < had[pick]:
                    had[pick] = float(odds)
        if len(had) == 3:
            out[mno] = had
    return out


def _results(daily_dir: str, date: str) -> dict[str, str]:
    """match_no -> actual had (胜/平/负)."""
    fp = f"{daily_dir}/{date}/tiered-plan-review.json"
    out: dict[str, str] = {}
    try:
        rev = json.load(open(fp))
    except (OSError, json.JSONDecodeError):
        return out
    for mno, r in (rev.get("results") or {}).items():
        had = r.get("had")
        if had in ("胜", "平", "负"):
            out[mno] = had
    return out


def build_samples(daily_dir: str) -> list[dict]:
    rows: list[dict] = []
    dates = sorted({os.path.basename(os.path.dirname(p))
                    for p in glob.glob(f"{daily_dir}/*/context.json")})
    for date in dates:
        had_map = _prematch_had(daily_dir, date)
        res = _results(daily_dir, date)
        for mno, had in had_map.items():
            actual = res.get(mno)
            if actual is None:
                continue  # not graded yet
            home_o, draw_o, away_o = had["胜"], had["平"], had["负"]
            fav_side = "胜" if home_o <= away_o else "负"
            fav_odds = min(home_o, away_o)
            und_side = "负" if fav_side == "胜" else "胜"
            und_odds = max(home_o, away_o)
            if fav_odds <= SOFT_LO:
                layer = "硬热"
            elif fav_odds <= SOFT_HI:
                layer = "软热"
            else:
                layer = "coinflip"
            if layer != "软热":
                continue  # 本表只追软热反面
            # §31.2 反面方向：冷 implied ≥ 平 implied -> 押冷，否则押平
            reverse_side = und_side if (1/und_odds) >= (1/draw_o) else "平"
            reverse_odds = und_odds if reverse_side == und_side else draw_o
            hit = (actual == reverse_side)
            ret = (reverse_odds - 1.0) if hit else -1.0
            rows.append({
                "date": date, "match_no": mno,
                "fav_side": fav_side, "fav_odds": round(fav_odds, 2),
                "reverse_side": reverse_side, "reverse_odds": round(reverse_odds, 2),
                "actual": actual, "hit": hit, "unit_return": round(ret, 3),
                # 对照：若跟随正路热门的结果
                "fav_hit": (actual == fav_side),
            })
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    rev_hits = sum(1 for r in rows if r["hit"])
    rev_roi = sum(r["unit_return"] for r in rows) / n
    fav_hits = sum(1 for r in rows if r["fav_hit"])
    # 正路对照 ROI：跟随软热正路（赔率=fav_odds），命中=fav_odds-1 否则 -1
    fav_roi = sum((r["fav_odds"] - 1.0) if r["fav_hit"] else -1.0
                  for r in rows) / n
    return {
        "n": n,
        "reverse_hit_rate": round(rev_hits / n, 3),
        "reverse_roi_per_unit": round(rev_roi, 3),
        "favourite_hit_rate": round(fav_hits / n, 3),
        "favourite_roi_per_unit": round(fav_roi, 3),
        "verdict": ("样本不足(<%d)，仅积累、勿决策" % MIN_SAMPLES) if n < MIN_SAMPLES
                   else ("软热反面有正回报溢价" if rev_roi > 0 and rev_roi > fav_roi
                         else "软热反面未显出优势"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-dir", default=DEFAULT_DAILY)
    ap.add_argument("--write", default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = build_samples(args.daily_dir)
    summ = summarize(rows)

    print(f"# §31 软热反面 paper-trade 追踪  (软热样本 n={summ['n']})")
    if rows:
        print(f"{'date':>10} {'场':>7} {'热方':>4}{'赔':>6} | "
              f"{'反面':>4}{'反赔':>6} {'实际':>4} {'中?':>3} {'回报':>7}")
        for r in rows:
            mark = "✓" if r["hit"] else "✗"
            print(f"{r['date']:>10} {r['match_no']:>7} {r['fav_side']:>4}"
                  f"{r['fav_odds']:>6.2f} | {r['reverse_side']:>4}"
                  f"{r['reverse_odds']:>6.2f} {r['actual']:>4} {mark:>3} "
                  f"{r['unit_return']:>+7.2f}")
    print("\n# 汇总（反面 vs 跟随正路对照）")
    if summ["n"]:
        print(f"  软热反面: 命中 {summ['reverse_hit_rate']:.1%} · "
              f"单位 ROI {summ['reverse_roi_per_unit']:+.3f}")
        print(f"  跟随正路: 命中 {summ['favourite_hit_rate']:.1%} · "
              f"单位 ROI {summ['favourite_roi_per_unit']:+.3f}")
        print(f"  结论: {summ['verdict']}")

    if args.write:
        json.dump({"summary": summ, "samples": rows},
                  open(args.write, "w"), ensure_ascii=False, indent=1)
        print(f"\nwrote {args.write}")


if __name__ == "__main__":
    main()
