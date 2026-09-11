"""任九/胜负彩 票面算术 + 账本操作（Roadmap D1+D2，确定性算术，零判断）。

**Why**：26103 构票期间盖率/P/门槛被临时脚本重算了十几次，ledger 靠内联 python 手写了
五次。本模块把两件事收编成命令——输入是**已成型的面集合**（与 `legs_audit` 同一 JSON），
输出是注数/命中率/回本门槛/需中奖注数，并自动过结构校验。**该买哪面不归它管。**

任九回本门槛的可观测换算（memory 落库常数）：返奖率恒 64.0% ⇒
`需全国中奖注数 ≤ 销量 × 0.64 ÷ 门槛`。奖金与我方命中率负相关，EV 一律用中位数口径。
"""
from __future__ import annotations

import json
from datetime import date
from functools import reduce
from pathlib import Path

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
PRIZE_MEDIAN = 6446          # 近 12 期任九单注中位(2026-08-09 口径)
SALES_DEFAULT = 13_000_000   # 任九销量近 12 期区间 ¥1.16-1.47 千万,取 ¥1300 万

LEDGER_FIELDS = ("issue", "kind", "stake_yuan", "tickets", "code")


def ticket_stats(legs: dict, *, price: int = 2, sales: float = SALES_DEFAULT,
                 prize_median: float = PRIZE_MEDIAN) -> dict:
    """legs = {场次: {faces, fair{home,draw,away}, ...}} → 票面算术包。"""
    if not legs:
        raise ValueError("空票面")
    per = []
    for no, leg in sorted(legs.items(), key=lambda kv: int(kv[0])):
        faces = str(leg["faces"])
        cov = sum(leg["fair"][FACE_KEYS[c]] for c in set(faces))
        per.append({"match_no": int(no), "name": leg.get("name", ""),
                    "faces": faces, "n_faces": len(set(faces)),
                    "coverage": round(cov, 4)})
    n = reduce(lambda a, b: a * b, (p["n_faces"] for p in per))
    prob = reduce(lambda a, b: a * b, (p["coverage"] for p in per))
    cost = n * price
    threshold = cost / prob if prob > 0 else float("inf")
    return {
        "legs": per,
        "n_legs": len(per),
        "notes": n,
        "cost": cost,
        "p_all": round(prob, 6),
        "expected_broken": round(sum(1 - p["coverage"] for p in per), 3),
        "breakeven": round(threshold),
        "breakeven_vs_median": round(threshold / prize_median, 2),
        "max_winners_for_breakeven": round(sales * 0.64 / threshold) if threshold else None,
        "ev_median": round(prob * prize_median - cost),
    }


def format_stats(s: dict, *, issue: str = "") -> str:
    out = [f"票面算术{'（' + issue + '）' if issue else ''}："
           f"{s['n_legs']} 腿 → {s['notes']} 注 ¥{s['cost']:,}"]
    for p in s["legs"]:
        t = {1: "单选", 2: "双选", 3: "全包"}[p["n_faces"]]
        out.append(f"  场{p['match_no']:>2} {p['faces']:<4}{t}  盖 {p['coverage']*100:>5.1f}%"
                   f"  {p['name']}")
    out.append(f"P(全中)={s['p_all']*100:.2f}%  期望断腿 {s['expected_broken']} 条")
    out.append(f"回本门槛 ¥{s['breakeven']:,}（中位 ¥{PRIZE_MEDIAN:,} 的 "
               f"{s['breakeven_vs_median']} 倍）｜"
               f"需全国中奖注数 ≤{s['max_winners_for_breakeven']:,}")
    out.append(f"中位口径 EV {s['ev_median']:+,}"
               "（⚠️奖金与我方命中率负相关，此为参考不是期待）")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# D2 · ledger 操作（替代内联 python）
# ---------------------------------------------------------------------------

def ledger_add(zucai_dir, row: dict) -> str:
    """追加一行入账。缺必填字段抛错；settled_at/hits/prize 留空由官方结算填。"""
    missing = [k for k in LEDGER_FIELDS if row.get(k) in (None, "")]
    if row.get("note") is None:
        missing.append("note")
    if missing:
        raise ValueError(f"ledger 行缺必填字段: {missing}")
    row.setdefault("ticket_id", "R1")
    row.setdefault("multiplier", 1)
    row.setdefault("purchased_at", date.today().isoformat())
    row.setdefault("order_no", None)
    row.setdefault("hits", None)
    row.setdefault("prize_yuan", 0)
    row.setdefault("settled_at", None)
    path = Path(zucai_dir) / "zucai-ledger.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return (f"入账 {row['issue']} {row['kind']} ¥{row['stake_yuan']:,}"
            f"（{row['tickets']} 注 × {row['multiplier']} 倍）")


def ledger_summary(zucai_dir, *, issue: str | None = None) -> str:
    path = Path(zucai_dir) / "zucai-ledger.jsonl"
    if not path.exists():
        return "(无 ledger)"
    rows = [json.loads(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]
    if issue:
        rows = [r for r in rows if str(r.get("issue")) == str(issue)]
    out = []
    stake = prize = 0.0
    trial_stake = 0.0
    for r in rows:
        # 体验/试玩方案登记但**不进净值**：混进合计会污染 user_exercise_record，
        # 而那条记分正是刹车条款（连续两期全灭→减半）的输入。
        trial = bool(r.get("trial"))
        if trial:
            trial_stake += r.get("stake_yuan") or 0
        else:
            stake += r.get("stake_yuan") or 0
            prize += r.get("prize_yuan") or 0
        st = r.get("settled_at") or "未结"
        out.append(f"  {r.get('issue')} {r.get('kind')} ¥{r.get('stake_yuan'):>6,} "
                   f"hits={r.get('hits')} 派奖 ¥{r.get('prize_yuan') or 0:,.0f} ({st})"
                   + ("  [体验方案·不计净值]" if trial else ""))
    tail = f"（另有体验方案 ¥{trial_stake:,.0f} 不计）" if trial_stake else ""
    out.append(f"合计: 投入 ¥{stake:,.0f} 派奖 ¥{prize:,.0f} 净 {prize-stake:+,.0f}{tail}")
    return "\n".join(out)
