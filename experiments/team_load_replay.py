"""F16 登记前回放（2026-10-09）：2025-26 赛季 jc-history × titan007 终盘 sharp fair。

判据冻结在设计稿 §4（docs/superpowers/specs/2026-10-09-team-load-ledger-design.md）之后才跑本脚本；
回放结果只进证据文档，不进判决（`rsi verdict` 只认 prospective）。

台账与结账都走生产代码：`nutmeg.decision.team_load`（出场索引 + 每队特征）与
`nutmeg.decision.rsi_grading.grade_f16_prospective`（同一个结账函数）。回放的「冻结时刻」取开球日
00:00、开球取 23:59——历史上不存在事后改台账的问题，只为满足前瞻门。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from nutmeg.decision.files import read_json
from nutmeg.decision.rsi_grading import bootstrap_residual_pp, grade_f16_prospective
from nutmeg.decision.team_load import build_index

_FACE = {"胜": "3", "平": "1", "负": "0"}


def replay_rows(data_dir: Path, date_from: str, date_to: str) -> list[dict]:
    index = build_index(data_dir)
    history = read_json(data_dir / "jczq" / "jc-history.json", {}) or {}
    rows = []
    for day in sorted(history):
        if not (date_from <= day <= date_to):
            continue
        closing = read_json(data_dir / "jczq" / "daily" / day / "closing_odds.json", {}) or {}
        on = date.fromisoformat(day)
        for code, match in history[day].items():
            outcome = ((match.get("sp") or {}).get("had") or {}).get("outcome")
            fair = ((closing.get(code) or {}).get("sharp") or {}).get("fair_probability")
            if outcome not in _FACE or not fair or not match.get("home") or not match.get("away"):
                continue
            home, away = index.features(match["home"], on), index.features(match["away"], on)
            rows.append({
                "key": f"{day}-{code}", "date": day, "actual": _FACE[outcome], "fair": fair,
                "home_load": home, "away_load": away,
                "team_load": {"captured_at": f"{day}T00:00:00+08:00",
                              "kickoff": f"{day}T23:59:00+08:00",
                              "load_diff_14": home["matches_14d"] - away["matches_14d"]},
            })
    return rows


def _side_residual(rows: list[dict], side_of) -> tuple[int, float, float, float]:
    resid = []
    for r in rows:
        side = side_of(r)
        if side is None:
            continue
        code = {"home": "3", "draw": "1", "away": "0"}[side]
        hit = "m" if r["actual"] == code else "x"
        resid.append({"actual": hit, "fair": {"m": r["fair"][side]}})
    ci = bootstrap_residual_pp(resid, face="m")
    return ci.n, ci.value_pp, ci.ci_low_pp, ci.ci_high_pp


def _one_sided(r: dict) -> str | None:
    """单边密集（一方 14 天 ≥4 场、另一方 ≤2）的更密一方；已在会话粗测里看过，只作对照。"""
    home, away = r["home_load"]["matches_14d"], r["away_load"]["matches_14d"]
    if home >= 4 and away <= 2:
        return "home"
    if away >= 4 and home <= 2:
        return "away"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".nutmeg-data")
    ap.add_argument("--from", dest="date_from", default="2025-08-15")
    ap.add_argument("--to", dest="date_to", default="2026-05-31")
    args = ap.parse_args()
    rows = replay_rows(Path(args.data_dir), args.date_from, args.date_to)
    in_season = [r for r in rows if r["home_load"]["rest_days"] is not None
                 and r["away_load"]["rest_days"] is not None]
    g = grade_f16_prospective(rows, window={"date_from": args.date_from})
    print(f"回放 {args.date_from}→{args.date_to}：可定价 {len(rows)} 场"
          f"（两队都有上一场 {len(in_season)}）")
    print(f"F16 主判据 |Δ14天场数|≥2 → 更密一方胜残差：n={g.n_cum}  "
          f"{g.metric_value_pp:+.1f}pp  95%CI[{g.ci_low_pp:+.1f},{g.ci_high_pp:+.1f}]")
    for label, side_of in (
        ("  其中 主更密", lambda r: "home" if r["team_load"]["load_diff_14"] >= 2 else None),
        ("  其中 客更密", lambda r: "away" if r["team_load"]["load_diff_14"] <= -2 else None),
        ("单边密集（≥4 vs ≤2）更密一方",
         _one_sided),
        ("对照 |Δ|≤1 主胜", lambda r: "home" if abs(r["team_load"]["load_diff_14"]) <= 1 else None),
    ):
        n, v, lo, hi = _side_residual(rows, side_of)
        print(f"{label}：n={n}  {v:+.1f}pp  95%CI[{lo:+.1f},{hi:+.1f}]")
    share = g.n_cum / len(rows) if rows else 0.0
    days = 150 / max(share * 20, 1e-9)
    print(f"触发率 {share * 100:.1f}%（按并集池每天约 20 场估，n=150 约需 {days:.0f} 天）")


if __name__ == "__main__":
    main()
