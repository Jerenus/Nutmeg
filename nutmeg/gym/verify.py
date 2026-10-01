"""验收门：gym 的结算必须复现真票在记分牌上的净额，否则后面的策略账全是废话。

真票来自 `betslips.jsonl`（`real` 策略原样回放）；记分牌 `tickets` 的键是 `jczq-YYYYMMDD` 与期号。
两张带 hafu 腿的票现有结算不支持 → 标 unsupported 单列，不计入合计差。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.gym.policies.real import load_real_slips
from nutmeg.gym.run import run_gym


def verify_real(data_dir: Path, *, scoreboard_path: Path | None = None) -> dict:
    data_dir = Path(data_dir)
    slips = load_real_slips(data_dir)
    days = sorted({s.placed_at[:10] for s in slips if s.channel == "jczq"})
    issues = sorted({str(s.issue) for s in slips if s.channel != "jczq" and s.issue})
    result = run_gym(data_dir=data_dir, policies=["real"], days=days, issues=issues,
                     run_id="verify", stop_loss=10**9)
    rows = [r for r in result.ledger if r["policy"] == "real"]
    unsupported = [r for r in rows if r.get("legal") or r.get("skipped") or r.get("net") is None]
    settled = [r for r in rows if r.get("net") is not None]
    gym_by_key: dict[str, float] = {}
    for r in settled:
        key = f"jczq-{r['key'].replace('-', '')}" if r["channel"] == "jczq" else r["issue"]
        gym_by_key[key] = gym_by_key.get(key, 0.0) + r["net"]
    try:
        sb_path = scoreboard_path or data_dir / "scoreboard.json"
        board = json.loads(sb_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        board = {}
    tickets = board.get("tickets") or {}
    comparison = []
    for key in sorted(gym_by_key):
        sb = tickets.get(key, {}).get("net") if isinstance(tickets.get(key), dict) else None
        comparison.append({"key": key, "gym_net": round(gym_by_key[key], 2), "scoreboard_net": sb,
                           "diff": (round(gym_by_key[key] - sb, 2) if isinstance(sb, int | float)
                                    else None)})
    compared = [c for c in comparison if c["diff"] is not None]
    return {
        "slips": len(slips), "settled": len(settled), "unsupported": unsupported,
        "comparison": comparison,
        "gym_total": round(sum(gym_by_key.values()), 2),
        "scoreboard_total": round(sum(c["scoreboard_net"] for c in compared), 2),
        "total_diff_on_compared": round(sum(c["diff"] for c in compared), 2),
        "uncompared_keys": [c["key"] for c in comparison if c["diff"] is None],
    }


def render_verify(out: dict) -> str:
    lines = [f"真票 {out['slips']} 张，已结 {out['settled']} 条，"
             f"不支持/未结 {len(out['unsupported'])} 条",
             "| 键 | gym 净 | 记分牌净 | 差 |", "|---|---|---|---|"]
    for c in out["comparison"]:
        sb = "—" if c["scoreboard_net"] is None else f"{c['scoreboard_net']:+,.0f}"
        diff = "—" if c["diff"] is None else f"{c['diff']:+,.0f}"
        lines.append(f"| {c['key']} | {c['gym_net']:+,.0f} | {sb} | {diff} |")
    lines.append(f"合计：gym {out['gym_total']:+,.0f}；"
                 f"记分牌（可比键）{out['scoreboard_total']:+,.0f}；"
                 f"可比键总差 {out['total_diff_on_compared']:+,.0f}")
    for r in out["unsupported"]:
        why = r.get("legal") or r.get("skipped") or "pending"
        lines.append(f"  ⚠️ {r['slip_id']} {r['channel']} {r['key']}：{why}")
    if out["uncompared_keys"]:
        lines.append(f"  记分牌无此键：{', '.join(out['uncompared_keys'])}")
    return "\n".join(lines)
