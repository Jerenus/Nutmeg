"""因子 4 —— 竞彩让球三路的跨盘残差（先补历史回测，再谈使用）。

**出生事故**：2026-09-14 我先向用户推荐了这个方法（四条 -2 盘全部显示让胜高估
6-12pp），**然后才说该补回测**——那是我自己违了自己的闸。本文件把顺序倒回来。

机制（先写死，再跑）：体彩的 ``had`` 与 ``hhad`` 是**两个独立定价、独立结算的池**，
但它们必须服从**同一个净胜球分布**。DC 从 had 拟合出 margin 分布再折成让球三路，
是同一分布的**另一种表达**，不是新信息。而 hhad 池**没有 had 池没有的信息源**
（体彩不接受锐盘资金、两池同一时刻同一庄）。因此任何 ``P_体彩hhad − P_DC`` 的系统
性偏离只可能是定价噪音或零售扭曲 → **DC 侧应当更准**。

预注册预测：``BSS(DC vs 体彩hhad) > 0``。**否决线**：bootstrap CI 下界 ≤ 0。

⛔结算源自检：脚本启动先用 ``results-0907.json``（API-Football + ESPN 两源一致）
校验 titan007 比分字段，不通过即拒绝跑。
"""
import json
import os
import random
import statistics
from pathlib import Path

from nutmeg.decision.dcfit import fit_match

DAILY = Path(".nutmeg-data/jczq/daily")
JCR = json.load(open(".nutmeg-data/jczq/jc-results.json"))
LEGS = ("让胜", "让平", "让负")


def _devig(odds: dict[str, float]) -> dict[str, float] | None:
    try:
        raw = {k: 1.0 / float(v) for k, v in odds.items()}
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    s = sum(raw.values())
    return None if s <= 0 else {k: v / s for k, v in raw.items()}


def selfcheck() -> None:
    truth = json.load(open(DAILY / "2026-09-07" / "results-0907.json"))
    day = JCR.get("2026-09-07", {})
    bad = []
    for m in truth["matches"]:
        r = day.get(m["no"])
        if not r:
            bad.append((m["no"], "缺席"))
            continue
        got = f"{r['ft_home']}:{r['ft_away']}"
        if got != m["ft"]:
            bad.append((m["no"], f"{got} vs 真值 {m['ft']}"))
    if bad:
        raise SystemExit(f"⛔结算源自检失败：{bad}")
    print(f"✅结算源自检：2026-09-07 {len(truth['matches'])}/{len(truth['matches'])} "
          f"场比分与两源赛果一致")


def cover(ft_h: int, ft_a: int, line: float) -> str:
    """体彩让球三路结算：整数盘热门恰胜 1 球落「让平」。"""
    net = (ft_h - ft_a) + line          # line 已含符号（-1 = 主队让一球）
    return "让胜" if net > 0 else ("让平" if net == 0 else "让负")


selfcheck()
seen, rows = set(), []
skipped = {"no_result": 0, "no_line": 0, "devig": 0, "dc": 0}
for d in sorted(os.listdir(DAILY)):
    path = DAILY / d / "sporttery_markets.json"
    if not path.exists():
        continue
    doc = json.load(open(path))
    for grp in doc.get("matchInfoList", []):
        for m in grp.get("subMatchList", []):
            biz, tag = m.get("businessDate"), m.get("matchNumStr")
            if not biz or not tag or (biz, tag) in seen:
                continue
            if biz != d:
                # 只用**比赛当日**的快照（离开球最近的价）
                continue
            had, hhad = m.get("had") or {}, m.get("hhad") or {}
            line_raw = hhad.get("goalLineValue")
            res = JCR.get(biz, {}).get(tag)
            if not res:
                skipped["no_result"] += 1
                continue
            if not line_raw:
                skipped["no_line"] += 1
                continue
            fair_had = _devig({"home": had.get("h"), "draw": had.get("d"),
                               "away": had.get("a")})
            fair_hh = _devig({"让胜": hhad.get("h"), "让平": hhad.get("d"),
                              "让负": hhad.get("a")})
            if not fair_had or not fair_hh:
                skipped["devig"] += 1
                continue
            line = float(line_raw)
            try:
                fit = fit_match(fair_had, hhad_line=str(int(line)))
                dc = fit.get("hhad_cover")
            except Exception:
                # noqa: BLE001 拟合失败=该场缺席
                dc = None
            if not dc or any(k not in dc for k in LEGS):
                skipped["dc"] += 1
                continue
            seen.add((biz, tag))
            rows.append({
                "date": biz, "tag": tag, "line": line,
                "market": fair_hh, "dc": {k: dc[k] for k in LEGS},
                "actual": cover(res["ft_home"], res["ft_away"], line),
            })

print(f"\n样本 n={len(rows)}  天={len({r['date'] for r in rows})}  跳过={skipped}")


def brier(p, a):
    return sum((p[k] - (1.0 if k == a else 0.0))**2 for k in LEGS)


bm = statistics.fmean(brier(r["market"], r["actual"]) for r in rows)
bd = statistics.fmean(brier(r["dc"], r["actual"]) for r in rows)
print(f"\nBrier  体彩hhad {bm:.5f}   DC(从had推) {bd:.5f}   "
      f"BSS(DC vs 体彩) {(1-bd/bm)*100:+.2f}%")

random.seed(7)
dd = [brier(r["market"], r["actual"]) - brier(r["dc"], r["actual"]) for r in rows]
bs = sorted(sum(random.choice(dd) for _ in dd) / len(dd) / bm * 100 for _ in range(4000))
w = sum(1 for x in dd if x > 1e-12)
print(f"bootstrap CI95[{bs[100]:+.2f},{bs[3899]:+.2f}]  配对 {w}:{len(dd)-w}")
print(f"闸：CI 下界 {'>0 → 过闸' if bs[100] > 0 else '≤0 → 不过闸'}")

print("\n① 逐路系统残差（体彩 − DC），正 = 体彩定价更高")
for k in LEGS:
    diffs = [r["market"][k] - r["dc"][k] for r in rows]
    act = sum(1 for r in rows if r["actual"] == k) / len(rows)
    mkt = statistics.fmean(r["market"][k] for r in rows)
    print(f"  {k}  Δ均值 {statistics.fmean(diffs)*100:+6.2f}pp   "
          f"实开 {act*100:5.1f}%  体彩期望 {mkt*100:5.1f}%"
          f"  DC 期望 {statistics.fmean(r['dc'][k] for r in rows)*100:5.1f}%")

print("\n② 按让球线分层（我昨天只看了四条 -2 盘）")
print(f"{'线':>6} {'n':>5} {'体彩Brier':>10} {'DC Brier':>10} {'BSS':>8}   让胜Δ")
for line in sorted({r["line"] for r in rows}):
    sub = [r for r in rows if r["line"] == line]
    if len(sub) < 20:
        continue
    m_ = statistics.fmean(brier(r["market"], r["actual"]) for r in sub)
    d_ = statistics.fmean(brier(r["dc"], r["actual"]) for r in sub)
    dw = statistics.fmean(r["market"]["让胜"] - r["dc"]["让胜"] for r in sub)
    print(f"{line:>+6.1f} {len(sub):>5} {m_:>10.5f} {d_:>10.5f} "
          f"{(1-d_/m_)*100:>+7.2f}%   {dw*100:+6.2f}pp")
