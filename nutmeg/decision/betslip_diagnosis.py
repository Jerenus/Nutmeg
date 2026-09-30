"""登记即诊断（Jun 2026-09-30）：每张实票登记时做两笔算术，写回票面、打印给人看。

1. **共享裸单**：与同日（竞彩）/ 同期（足彩）已登记的实购票共享的单选腿，以及
   「这些票一起死」的联合概率 1 − Π P(面)（缺 fair 的腿不算，明写）。
2. **对照处方**：足彩对 `<issue>-judgment-v1.json` 的 action，竞彩对当日 `jczq-legs-base.json`
   的表态面集合——逐腿记「相同 / 收窄 / 处方外（含翻面）/ 无处方」。

出生事故 2026-09-28：五张竞彩票共享 004 土耳其主裸单（按市场价五票同死 ≥64%），两张足彩票
把处方双选压成裸单——全部经 `betslip register` 登记，审计门从没看见它们。
⛔只算术、只记录：不阻断登记，不改票面，不产生判断。
"""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg

FACE_OF_SELECTION = {"home": "3", "draw": "1", "away": "0", "3": "3", "1": "1", "0": "0"}
FACE_ORDER = "310"
ZUCAI_CHANNELS = ("renjiu", "shengfucai")


def _faces(leg: SlipLeg) -> str:
    chosen = {FACE_OF_SELECTION.get(str(s)) for s in leg.selections}
    return "".join(f for f in FACE_ORDER if f in chosen)


def peers(slip: BetSlip, slips: list[BetSlip]) -> list[BetSlip]:
    """同一盘面上的其它实购票：竞彩＝同下单日，足彩＝同期号（任九与胜负彩互为同伴）。"""
    out = []
    for other in slips:
        if other.slip_id == slip.slip_id or not other.purchased:
            continue
        if slip.channel == "jczq":
            same = other.channel == "jczq" and str(other.placed_at)[:10] == str(slip.placed_at)[:10]
        else:
            same = other.channel in ZUCAI_CHANNELS and other.issue == slip.issue
        if same:
            out.append(other)
    return out


def _naked(leg: SlipLeg) -> tuple | None:
    if len(leg.selections) != 1:
        return None
    return (leg.key, leg.market, leg.line, FACE_OF_SELECTION.get(str(leg.selections[0]),
                                                                 str(leg.selections[0])))


def shared_naked_legs(slip: BetSlip, others: list[BetSlip]) -> list[dict]:
    """本票的单选腿里，哪些在别的票上也是同一个单选。"""
    index: dict[tuple, list[str]] = {}
    for other in others:
        for leg in other.legs:
            key = _naked(leg)
            if key is not None:
                index.setdefault(key, []).append(other.slip_id)
    shared = []
    for leg in slip.legs:
        key = _naked(leg)
        if key is None or key not in index:
            continue
        face = key[3]
        p_face = None
        if leg.fair and leg.market == "had":
            p_face = leg.fair.get({"3": "home", "1": "draw", "0": "away"}.get(face, face))
        shared.append({
            "key": leg.key, "market": leg.market, "line": leg.line, "face": face,
            "p_face": None if p_face is None else round(float(p_face), 4),
            "slip_ids": sorted({slip.slip_id, *index[key]}),
        })
    return shared


def joint_death(shared: list[dict]) -> dict:
    """至少一条共享裸单不中 ⇒ 所有含它的票同死；缺 P 的腿不算、明写。"""
    known = [row["p_face"] for row in shared if row["p_face"] is not None]
    survive = 1.0
    for p in known:
        survive *= p
    return {
        "n_shared": len(shared),
        "n_priced": len(known),
        "p_all_die_at_least": None if not known else round(1 - survive, 4),
    }


def prescription_for(slip: BetSlip, data_dir: Path) -> dict[str, str]:
    """足彩：judgment-v1 的 action；竞彩：当日 legs-base 的表态面集合。找不到 → 空。"""
    data_dir = Path(data_dir)
    try:
        if slip.channel in ZUCAI_CHANNELS:
            doc = json.loads((data_dir / "zucai" / f"{slip.issue}-judgment-v1.json")
                             .read_text(encoding="utf-8"))
            return {str(k): str(v.get("action") or "") for k, v in doc.items()
                    if isinstance(v, dict) and v.get("action")}
        day = str(slip.placed_at)[:10]
        doc = json.loads((data_dir / "jczq" / "daily" / day / "jczq-legs-base.json")
                         .read_text(encoding="utf-8"))
        return {code: str(leg.get("faces") or "") for code, leg in doc["legs"].items()
                if leg.get("faces")}
    except (OSError, ValueError, KeyError):
        return {}


def narrowing(slip: BetSlip, prescription: dict[str, str]) -> dict:
    out: dict[str, list[str]] = {"same": [], "narrower": [], "off_prescription": [],
                                 "unprescribed": [], "other_market": []}
    for leg in slip.legs:
        if leg.market != "had":
            out["other_market"].append(leg.key)
            continue
        pres = prescription.get(leg.key)
        if not pres:
            out["unprescribed"].append(leg.key)
            continue
        mine, theirs = set(_faces(leg)), set(pres)
        if mine == theirs:
            out["same"].append(leg.key)
        elif mine < theirs:
            out["narrower"].append(leg.key)
        else:
            out["off_prescription"].append(leg.key)
    return out


def diagnose(slip: BetSlip, others: list[BetSlip], prescription: dict[str, str]) -> dict:
    shared = shared_naked_legs(slip, others)
    joint = joint_death(shared)
    narrow = narrowing(slip, prescription)
    lines = []
    if shared:
        keys = "、".join(f"{r['key']}{r['face']}" for r in shared)
        p = joint["p_all_die_at_least"]
        n_slips = len({sid for r in shared for sid in r["slip_ids"]})
        lines.append(
            f"⚠️共享裸单 {len(shared)} 条（{keys}）与 {n_slips - 1} 张票同押"
            + (f"；这些票一起死 ≥{p * 100:.0f}%" if p is not None else "")
            + (f"（{joint['n_shared'] - joint['n_priced']} 腿缺 fair 未计）"
               if joint["n_shared"] > joint["n_priced"] else "")
        )
    if narrow["narrower"] or narrow["off_prescription"]:
        lines.append(
            "⚠️对照处方：收窄 " + (",".join(narrow["narrower"]) or "无")
            + "；处方外/翻面 " + (",".join(narrow["off_prescription"]) or "无")
            + "（8/08 铁律：压预算丢整场，不降档）"
        )
    if not lines:
        lines.append("诊断：无共享裸单；票面未比处方窄")
    return {"shared_naked": shared, "joint_death": joint, "narrowing": narrow, "lines": lines}
