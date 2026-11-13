# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""Jun 任九实票的防守账（2026-11-07，接 defense-width）。

逐腿按一赔 P 分档看单与双的结果；反事实：把一赔 ≥阈值的双改成该场一赔单，省多少、丢几次全中。
派奖按官方任九单注 × 倍数，只算九场全对；未事前登记，只展示。
用法：uv run python experiments/prescreen/2026-11-07-defense-real-tickets.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")
from nutmeg.gym.prizes import load_prizes

MAP = {"home": "3", "draw": "1", "away": "0"}
BANDS = ((.65, 1.01, "≥65"), (.50, .65, "50–65"), (0, .50, "<50"))


def main():
    prizes = load_prizes(Path(".nutmeg-data/zucai"))
    R = [json.loads(l) for l in open(".nutmeg-data/betslips.jsonl")]
    T = [r for r in R if r.get("channel") == "renjiu" and r.get("purchased") is not False]
    legs_ct = defaultdict(Counter)
    tick = []
    skipped = 0
    for r in T:
        pr = prizes.get(str(r.get("issue")))
        if not pr or not pr.get("results"):
            skipped += 1
            continue
        res = pr["results"].split()
        rows = []
        for leg in r.get("legs") or []:
            i = int(leg["key"]) - 1
            sel = [MAP.get(x, x) for x in (leg.get("selections") or [])]
            fair = {MAP.get(k, k): v for k, v in (leg.get("fair") or {}).items()}
            if not fair:
                continue
            top = max(fair, key=fair.get)
            rows.append(dict(sel=sel, p=fair[top], top=top, a=res[i]))
        if len(rows) != 9:
            skipped += 1
            continue
        for x in rows:
            band = next(b for lo, hi, b in BANDS if lo <= x["p"] < hi)
            k = len(x["sel"])
            ok = x["a"] in x["sel"] or x["a"] == "*"
            if k == 1:
                legs_ct[band]["单对" if ok else "单死"] += 1
            else:
                cat = "穿" if not ok else ("白" if x["a"] == x["top"] else "到")
                legs_ct[band][("双" if k == 2 else "包") + cat] += 1
        stake = float(r.get("stake_yuan") or 0)
        win = all(x["a"] in x["sel"] or x["a"] == "*" for x in rows)
        prize = ((pr.get("renjiu") or {}).get("stake_amount") or 0) * (r.get("multiplier") or 1) if win else 0
        tick.append(dict(id=r["slip_id"], rows=rows, stake=stake, win=win, prize=prize, issue=str(r.get("issue"))))
    print("任九实票", len(tick), "跳过", skipped, "总投入", sum(t["stake"] for t in tick), "全中", sum(t["win"] for t in tick), "派奖", sum(t["prize"] for t in tick))
    for _, _, b in BANDS:
        c = legs_ct[b]
        d = c["双白"] + c["双到"] + c["双穿"]; s = c["单对"] + c["单死"]; f = c["包白"] + c["包到"]
        print(b, f"单 {s}：对 {c['单对']} 死 {c['单死']}（死 {c['单死']/max(s,1)*100:.0f}%）｜双 {d}：白防 {c['双白']}（{c['双白']/max(d,1)*100:.0f}%）防到 {c['双到']}（{c['双到']/max(d,1)*100:.0f}%）防穿 {c['双穿']}（{c['双穿']/max(d,1)*100:.0f}%）｜包 {f}：白 {c['包白']} 到 {c['包到']}")
    for th in (.60, .65, .70):
        cost = kept = lost = pay_k = 0.0
        lostids = []
        for t in tick:
            f = 1.0
            alive = t["win"]
            for x in t["rows"]:
                if len(x["sel"]) >= 2 and x["p"] >= th and x["top"] in x["sel"]:
                    f /= len(x["sel"])
                    if x["a"] != x["top"] and x["a"] != "*":
                        alive = False
            cost += t["stake"] * f
            if alive:
                kept += 1
                pay_k += t["prize"]
            elif t["win"]:
                lost += 1
                lostids.append((t["id"], t["prize"]))
        print(f"一赔≥{th:.2f} 的双和包改单：投入 {sum(x['stake'] for x in tick):,.0f}→{cost:,.0f}，全中保留 {kept:.0f}，丢 {lost:.0f} {lostids}，派奖 {pay_k:,.0f}")
    print("全中票", [(t["id"], t["stake"], t["prize"]) for t in tick if t["win"]])
    by = defaultdict(float)
    for t in tick:
        by[t["issue"]] += t["stake"]
    print("期数", len(by), "期均 %.0f" % (sum(by.values()) / len(by)))
    D = sorted((v.get("draw_date") or "")[:7] for v in prizes.values())
    c = Counter(D)
    print("每月期数", sorted(c.items())[-8:])


if __name__ == "__main__":
    main()
