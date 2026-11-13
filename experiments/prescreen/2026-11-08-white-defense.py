# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""白防线与多票期（2026-11-08，Jun：过度防御，有没有针对白防的缩减和人性面的资金优化）。

① 任九实票的双按 p1/(p1+p2) 分线：线以上的双有多少白防、全改单省多少、丢几次全中。
② 多票期里中奖的是第几张（按价、按登记顺序）。③ 投入随上期结果的变化。
派奖按官方任九单注 × 倍数，只算九场全对；n=5 次全中，未事前登记，只展示。
用法：uv run python experiments/prescreen/2026-11-08-white-defense.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")
from nutmeg.gym.prizes import load_prizes

MAP = {"home": "3", "draw": "1", "away": "0"}


def main():
    prizes = load_prizes(Path(".nutmeg-data/zucai"))
    slips = [json.loads(l) for l in open(".nutmeg-data/betslips.jsonl")]
    tick = []
    for r in slips:
        pr = prizes.get(str(r.get("issue")), {})
        if r.get("channel") != "renjiu" or r.get("purchased") is False or not pr.get("results"):
            continue
        res = pr["results"].split()
        rows = []
        for leg in r["legs"]:
            f = {MAP.get(k, k): v for k, v in (leg.get("fair") or {}).items()}
            if f:
                rows.append(dict(sel=[MAP.get(x, x) for x in leg.get("selections") or []],
                                 o=sorted(f, key=lambda k: -f[k]), f=f, a=res[int(leg["key"]) - 1]))
        if len(rows) != 9:
            continue
        win = all(x["a"] in x["sel"] or x["a"] == "*" for x in rows)
        prize = ((pr.get("renjiu") or {}).get("stake_amount") or 0) * (r.get("multiplier") or 1) if win else 0
        tick.append(dict(id=r["slip_id"], issue=str(r["issue"]), rows=rows, stake=float(r.get("stake_yuan") or 0),
                         win=win, prize=prize))
    total = sum(t["stake"] for t in tick)
    print("任九票", len(tick), "投入", total)
    for th in (.85, .80, .75, .70):
        n = white = 0
        cost = 0.0
        lost = []
        for t in tick:
            f, alive = 1.0, t["win"]
            for x in t["rows"]:
                if len(x["sel"]) == 2 and x["o"][0] in x["sel"]:
                    o1 = x["o"][0]
                    o2 = next(c for c in x["sel"] if c != o1)
                    if x["f"][o1] / (x["f"][o1] + x["f"][o2]) >= th:
                        n += 1
                        white += x["a"] == o1
                        f /= 2
                        alive = alive and x["a"] in (o1, "*")
            cost += t["stake"] * f
            if t["win"] and not alive:
                lost.append((t["id"], t["prize"]))
        print(f"线 {th:.2f}：双 {n} 条，白防 {white}（{white / max(n, 1):.0%}），投入 {total:,.0f}→{cost:,.0f}，丢全中 {lost}")
    by = defaultdict(list)
    for r in slips:
        if r.get("channel") in ("renjiu", "shengfucai") and r.get("purchased") is not False and r.get("issue"):
            by[str(r["issue"])].append(r)
    for t in tick:
        if t["win"]:
            v = by[t["issue"]]
            price = sorted(v, key=lambda x: -(x.get("stake_yuan") or 0))
            print("中奖期", t["issue"], "张数", len(v), t["id"], "按价第", [x["slip_id"] for x in price].index(t["id"]) + 1,
                  "登记第", [x["slip_id"] for x in v].index(t["id"]) + 1, "奖金", t["prize"])


if __name__ == "__main__":
    main()
