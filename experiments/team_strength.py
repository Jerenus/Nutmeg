#!/usr/bin/env python
"""客观实力指标：每队本赛季「相对市场的超额表现」，只用赛前可得的客观数据。

原料全部已在磁盘上：
  · 竞彩板 `daily/<日>/sporttery_markets.json`（队名/联赛/matchId）× `jc-results.json`（比分）
    × `daily/<日>/closing_odds.json`（titan007 终盘，sharp 口径）或 `bold_odds.json`（读时盘）
  · 语料 v2 里带队名的内核行（forecast prior × 赛果）
  · 足彩期次：`<期>-issue.json` 队名 × `official-results.json` × 语料 fair（队名需与竞彩同名才并入）

对每场：市场期望积分 E = 3·p(胜) + 1·p(平)，实际积分 A ∈ {3,1,0}，残差 = A − E。
每队：场次、胜平负、进失球、市场期望积分、残差均值、收缩后残差（×n/(n+5)）、主客拆分、
市场隐含强度（作主时 p(主胜) / 作客时 p(客胜) 的均值）。

⛔这不是「谁更强」的排名——终盘已经是最好的客观实力估计；这里量的是**市场之外**的那部分：
一支队本赛季是否系统性地打得比它的价格好或差。它有没有预测力，用同一份数据做前瞻式检验：
每场只用开球前已完成的比赛算两队的累计残差，看残差差能不能预测主胜相对 p(主胜) 的偏离。

    uv run python experiments/team_strength.py build [--since 2026-07-01] [--min-n 5]
    uv run python experiments/team_strength.py test  [--since ...] [--n-perm 1000]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
J = ROOT / ".nutmeg-data" / "jczq"
Z = ROOT / ".nutmeg-data" / "zucai"
CORPUS = ROOT / "experiments" / "corpus-v2.json"
OUT = ROOT / ".nutmeg-data" / "analytics" / "team_strength.json"
POINTS = {"3": (3, 0), "1": (1, 1), "0": (0, 3)}


def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _sporttery_index() -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for day in sorted(os.listdir(J / "daily")) if (J / "daily").is_dir() else []:
        doc = _load(J / "daily" / day / "sporttery_markets.json", {}) or {}
        for group in doc.get("matchInfoList") or []:
            for sub in (group or {}).get("subMatchList") or []:
                code = sub.get("matchNumStr")
                if not code:
                    continue
                index.setdefault(
                    (sub.get("businessDate") or day, code),
                    {
                        "home": sub.get("homeTeamAbbName"),
                        "away": sub.get("awayTeamAbbName"),
                        "league": sub.get("leagueAbbName"),
                        "match_date": sub.get("matchDate") or day,
                    },
                )
    return index


def _prev(day: str) -> str:
    return date.fromordinal(date.fromisoformat(day).toordinal() - 1).isoformat()


def _closing_fair(day: str, code: str) -> dict | None:
    for d in (day, _prev(day)):
        entry = (_load(J / "daily" / d / "closing_odds.json", {}) or {}).get(code)
        if entry and entry.get("sharp") and entry["sharp"].get("fair_probability"):
            return entry["sharp"]["fair_probability"]
    return None


def _bold_fair(day: str, code: str) -> dict | None:
    for d in (day, _prev(day)):
        mk = (_load(J / "daily" / d / "bold_odds.json", {}) or {}).get(code) or {}
        fair = ((mk.get("match_winner") or {}).get("fair_probability")) or None
        if fair:
            return fair
    return None


def match_table() -> list[dict]:
    """去重后的比赛表：date, league, home, away, gh, ga, actual, fair, source。"""
    rows: dict[tuple[str, str, str], dict] = {}
    index = _sporttery_index()
    results = _load(J / "jc-results.json", {}) or {}
    for day, board in results.items():
        for code, got in (board or {}).items():
            meta = index.get((day, code))
            if not meta or not meta.get("home") or got.get("ft_home") is None:
                continue
            fair = _closing_fair(day, code) or _bold_fair(day, code)
            if not fair:
                continue
            gh, ga = int(got["ft_home"]), int(got["ft_away"])
            actual = "3" if gh > ga else "0" if ga > gh else "1"
            key = (meta["match_date"], meta["home"], meta["away"])
            rows.setdefault(
                key,
                dict(
                    date=meta["match_date"], league=meta.get("league"), home=meta["home"],
                    away=meta["away"], gh=gh, ga=ga, actual=actual, fair=fair, source="jczq",
                ),
            )
    corpus = (_load(CORPUS, {}) or {}).get("rows") or []
    known = {name for k in rows for name in (k[1], k[2])}
    for r in corpus:
        name = r.get("name") or ""
        if " vs " in name:
            home, away = name.split(" vs ", 1)
        elif "·" in name and "-" in name:
            home, away = name.split("·", 1)[0].split("-", 1)
        else:
            continue
        if not r.get("date") or r.get("actual") not in POINTS:
            continue
        key = (r["date"], home, away)
        if key in rows or not (r.get("fair") or {}):
            continue
        goals = r.get("goals") or [None, None]
        rows[key] = dict(
            date=r["date"], league=None, home=home, away=away, gh=goals[0], ga=goals[1],
            actual=r["actual"], fair=r["fair"], source=r["src"],
            name_known=home in known and away in known,
        )
    return sorted(rows.values(), key=lambda m: m["date"])


def _expected(fair: dict) -> tuple[float, float]:
    return 3 * fair["home"] + fair["draw"], 3 * fair["away"] + fair["draw"]


def team_index(matches: list[dict], *, since: str, min_n: int) -> dict[str, dict]:
    teams: dict[str, dict] = defaultdict(
        lambda: dict(n=0, w=0, d=0, l=0, gf=0, ga=0, pts=0, exp=0.0, home_n=0, home_resid=0.0,
                     away_n=0, away_resid=0.0, market_strength=0.0, leagues=set(), last5=[])
    )
    for m in matches:
        if m["date"] < since:
            continue
        eh, ea = _expected(m["fair"])
        ph, pa = POINTS[m["actual"]]
        for side, name, pts, exp, gf, ga, strength in (
            ("home", m["home"], ph, eh, m["gh"], m["ga"], m["fair"]["home"]),
            ("away", m["away"], pa, ea, m["ga"], m["gh"], m["fair"]["away"]),
        ):
            t = teams[name]
            t["n"] += 1
            t["w" if pts == 3 else "d" if pts == 1 else "l"] += 1
            if gf is not None and ga is not None:
                t["gf"] += gf
                t["ga"] += ga
            t["pts"] += pts
            t["exp"] += exp
            t[f"{side}_n"] += 1
            t[f"{side}_resid"] += pts - exp
            t["market_strength"] += strength
            if m.get("league"):
                t["leagues"].add(m["league"])
            t["last5"].append(round(pts - exp, 3))
    out = {}
    for name, t in teams.items():
        if t["n"] < min_n:
            continue
        resid = (t["pts"] - t["exp"]) / t["n"]
        out[name] = dict(
            n=t["n"], record=f"{t['w']}-{t['d']}-{t['l']}", pts=t["pts"], gf=t["gf"], ga=t["ga"],
            market_expected_pts=round(t["exp"], 2),
            resid_per_match=round(resid, 3),
            resid_shrunk=round(resid * t["n"] / (t["n"] + 5), 3),
            home_resid=round(t["home_resid"] / t["home_n"], 3) if t["home_n"] else None,
            away_resid=round(t["away_resid"] / t["away_n"], 3) if t["away_n"] else None,
            market_strength=round(t["market_strength"] / t["n"], 3),
            last5_resid=round(sum(t["last5"][-5:]) / len(t["last5"][-5:]), 3),
            leagues=sorted(t["leagues"]),
        )
    return out


def prematch_rows(matches: list[dict], *, since: str) -> list[dict]:
    """前瞻式行：每场只用开球日之前已完成的比赛计算两队累计残差。"""
    history: dict[str, list[tuple[str, float]]] = defaultdict(list)
    rows = []
    for m in matches:
        eh, ea = _expected(m["fair"])
        ph, pa = POINTS[m["actual"]]

        def cum(name: str, before: str) -> tuple[float | None, int]:
            past = [v for d, v in history[name] if since <= d < before]
            return (sum(past) / len(past) if past else None), len(past)

        rh, nh = cum(m["home"], m["date"])
        ra, na = cum(m["away"], m["date"])
        if m["date"] >= since:
            rows.append(
                dict(
                    date=m["date"], home=m["home"], away=m["away"],
                    factor=(rh - ra) if rh is not None and ra is not None else None,
                    n_hist=min(nh, na),
                    face_hit=int(m["actual"] == "3"), fair=m["fair"]["home"],
                    provably_prospective=True,
                )
            )
        history[m["home"]].append((m["date"], ph - eh))
        history[m["away"]].append((m["date"], pa - ea))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["build", "test"])
    ap.add_argument("--since", default="2026-07-01")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--min-hist", type=int, default=3, help="test: 两队各至少已赛几场")
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    matches = match_table()
    by_source = defaultdict(int)
    for m in matches:
        by_source[m["source"]] += 1
    print(
        f"比赛表 {len(matches)} 场 {dict(by_source)}，"
        f"日期 {matches[0]['date']} → {matches[-1]['date']}"
    )
    if args.command == "build":
        return _build(matches, args)
    return _test(matches, args)


def _build(matches: list[dict], args) -> int:
    index = team_index(matches, since=args.since, min_n=args.min_n)
    ranked = sorted(index.items(), key=lambda kv: -kv[1]["resid_shrunk"])
    print(f"since {args.since}，{len(index)} 队达到 ≥{args.min_n} 场\n")
    head = f"{'队':<12}{'场':>3}{'战绩':>9}{'积分':>5}{'市场期望':>8}{'残差/场':>8}{'收缩':>7}"
    print(head + f"{'市场强度':>8}  联赛")
    for name, t in ranked[:15] + [("…", None)] + ranked[-10:]:
        if t is None:
            print("…")
            continue
        line = (
            f"{name:<12}{t['n']:>3}{t['record']:>9}{t['pts']:>5}{t['market_expected_pts']:>8}"
            f"{t['resid_per_match']:>+8.2f}{t['resid_shrunk']:>+7.2f}{t['market_strength']:>8.2f}"
        )
        print(line + f"  {'/'.join(t['leagues'])[:14]}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "built_from": len(matches),
                "since": args.since,
                "min_n": args.min_n,
                "definition": (
                    "resid = actual points - (3*p_win + p_draw) from closing fair; "
                    "shrunk = resid * n/(n+5)"
                ),
                "teams": dict(ranked),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n写入 {args.out}")
    return 0


def _test(matches: list[dict], args) -> int:
    from experiments.noise_floor import permutation_floor

    rows = [
        r
        for r in prematch_rows(matches, since=args.since)
        if r["factor"] is not None and r["n_hist"] >= args.min_hist
    ]
    if len(rows) < 10:
        print(f"可用行 {len(rows)}，不足以检验")
        return 0
    rows.sort(key=lambda r: r["date"])
    half = len(rows) // 2
    print(
        f"前瞻式检验：{len(rows)} 场两队各≥{args.min_hist} 场历史；"
        "因子=主队累计残差−客队累计残差；目标=主胜相对 p(主胜) 的残差"
    )
    for label, part in (("全体", rows), ("训练窗", rows[:half]), ("测试窗", rows[half:])):
        r = permutation_floor(part, "factor", "face_hit_rate_resid_pp", n_perm=args.n_perm)
        print(
            f"  {label:<4} n={r['n']:<4} 斜率={r['observed_pp']:+.2f}pp/单位残差 "
            f"地板[{r['floor_p2_5']:+.2f},{r['floor_p97_5']:+.2f}] p={r['p_value']:.3f} "
            f"→ {r['verdict']}"
        )
    buckets = (
        ("主队更超预期(差>+0.3)", lambda r: r["factor"] > 0.3),
        ("客队更超预期(差<-0.3)", lambda r: r["factor"] < -0.3),
    )
    for label, sel in buckets:
        part = [r for r in rows if sel(r)]
        if part:
            act = sum(r["face_hit"] for r in part) / len(part)
            exp = sum(r["fair"] for r in part) / len(part)
            print(
                f"  {label}: n={len(part)} 主胜实际={act * 100:.1f}% "
                f"价格={exp * 100:.1f}% R={(act - exp) * 100:+.1f}pp"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
