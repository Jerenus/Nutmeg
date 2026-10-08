"""审票运行器（2026-10-01）：一张票 → 同伴诊断（共享裸单）+ 审票（V1/V2/V3）。

`betslip preview/register`、足彩初稿、当日报告、判决页都走这一条路，口径只有一个。
只读：不登记、不写盘。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, load_slips
from nutmeg.decision.faces import CODE_OF


def _legs_base(data_dir: Path, issue: str) -> dict:
    if not issue:
        return {}
    try:
        doc = json.loads((Path(data_dir) / "zucai" / f"{issue}-legs-base.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc.get("legs") or {}


def issue_belief(data_dir: Path, issue: str) -> dict[str, dict]:
    """legs-base 的 fair（＝判断概率）→ {场号: 分布}。"""
    return {no: leg["fair"] for no, leg in _legs_base(data_dir, issue).items() if leg.get("fair")}


def issue_market(data_dir: Path, issue: str) -> dict[str, dict]:
    """legs-base 的 prior（＝市场分布），缺 prior 用 fair。"""
    return {no: (leg.get("prior") or leg.get("fair"))
            for no, leg in _legs_base(data_dir, issue).items()
            if leg.get("prior") or leg.get("fair")}


def review_slip(slip: BetSlip, data_dir: Path, *, slips: list[BetSlip] | None = None,
                model: dict | None = None, market: dict | None = None) -> dict:
    """→ {diagnosis, ratio, detail, verdicts, vetoed, lines}。同伴＝本期/本日其它实购票。"""
    from nutmeg.decision.betslip_diagnosis import (
        cross_translators,
        diagnose,
        peers,
        prescription_for,
    )
    from nutmeg.decision.review import prize_model, review

    data_dir = Path(data_dir)
    slips = load_slips(data_dir) if slips is None else slips
    cross = cross_translators(slip, slips, data_dir)
    diagnosis = diagnose(slip, peers(slip, slips, cross), prescription_for(slip, data_dir), cross)
    if market is None and slip.channel != "jczq":
        market = issue_market(data_dir, slip.issue)
    out = review(slip, diagnosis, prize_model=model or prize_model(data_dir), market=market)
    return {"diagnosis": diagnosis, **out}


def _legs_text(slip: BetSlip) -> str:
    if slip.channel != "jczq":
        return " ".join(f"{no}:{fs}" for no, fs in
                        sorted(slip.faces.items(), key=lambda kv: int(kv[0])))
    parts = []
    for leg in slip.legs:
        faces = "".join(CODE_OF.get(s, s) for s in leg.selections)
        line = f" 让{leg.line}" if leg.market == "hhad" and leg.line is not None else ""
        parts.append(f"{leg.key}{line} {faces}")
    combo = "/".join(str(c) for c in slip.combo_sizes) if slip.combo_sizes else ""
    return " + ".join(parts) + (f"（{combo} 串 1）" if combo else "")


def slip_summary(slip: BetSlip, data_dir: Path, *, slips: list[BetSlip] | None = None,
                 model: dict | None = None) -> dict:
    """面板用的一张票：票面、注金、P、审票行、是否否决。审票失败不塌面板。"""
    try:
        rv = review_slip(slip, data_dir, slips=slips, model=model)
        lines, vetoed, ratio = rv["lines"], rv["vetoed"], rv["ratio"]
    except Exception as exc:  # noqa: BLE001 —— 老票缺字段/内核缺文件
        lines, vetoed, ratio = [f"审票失败：{exc!r}"[:160]], False, None
    p = slip.hit_probability
    return {"slip_id": slip.slip_id, "channel": slip.channel, "issue": slip.issue,
            "placed_at": slip.placed_at, "purchased": slip.purchased,
            "stake_yuan": slip.stake_yuan, "notes": slip.notes, "multiplier": slip.multiplier,
            "p_all": round(p, 4) if p is not None else None, "ratio": ratio,
            "text": _legs_text(slip), "note": slip.note, "vetoed": vetoed, "lines": lines}
