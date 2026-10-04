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
from pathlib import Path

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
PRIZE_MEDIAN = 6446          # 近 12 期任九单注中位(2026-08-09 口径)
SALES_DEFAULT = 13_000_000   # 任九销量近 12 期区间 ¥1.16-1.47 千万,取 ¥1300 万

LEDGER_FIELDS = ("issue", "kind", "stake_yuan", "tickets", "code")


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
