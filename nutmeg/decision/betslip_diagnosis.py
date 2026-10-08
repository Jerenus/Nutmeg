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
from nutmeg.decision.faces import CODE_OF, FACE_OF
from nutmeg.decision.files import read_json
from nutmeg.decision.zucai_identity import load_channel_map

FACE_OF_SELECTION = {**CODE_OF, **{code: code for code in FACE_OF}}
FACE_ORDER = "310"
ZUCAI_CHANNELS = ("renjiu", "shengfucai")


def _faces(leg: SlipLeg) -> str:
    chosen = {FACE_OF_SELECTION.get(str(s)) for s in leg.selections}
    return "".join(f for f in FACE_ORDER if f in chosen)


def _channel_map(data_dir: Path, issue: str) -> dict[str, str]:
    """{竞彩 match_id: 足彩场号（腿 key 写法）}。"""
    return {mid: str(no) for mid, no in load_channel_map(Path(data_dir) / "zucai", issue).items()}


def _code_of_match(data_dir: Path, day: str) -> dict[str, str]:
    doc = read_json(Path(data_dir) / "jczq" / "daily" / day / "jczq-legs-base.json") or {}
    return {str(leg.get("match_id")): code for code, leg in (doc.get("legs") or {}).items()}


def cross_translators(slip: BetSlip, slips: list[BetSlip], data_dir: Path) -> dict[str, dict]:
    """跨渠道同伴：{其它票 slip_id: {它的腿 key → 本票的 key}}，只靠 channel-map 显式映射，
    映射不到的腿不比（身份不许猜，26122）。09-28 土耳其主同时是竞彩五票与足彩两票的死点。"""
    out: dict[str, dict] = {}
    if slip.channel == "jczq":
        code_of = _code_of_match(data_dir, str(slip.placed_at)[:10])
        for other in slips:
            if other.channel not in ZUCAI_CHANNELS or not other.purchased or not other.issue:
                continue
            trans = {no: code_of[mid] for mid, no in _channel_map(data_dir, other.issue).items()
                     if mid in code_of}
            if trans:
                out[other.slip_id] = trans
    else:
        cmap = _channel_map(data_dir, slip.issue)
        for other in slips:
            if other.channel != "jczq" or not other.purchased:
                continue
            code_of = _code_of_match(data_dir, str(other.placed_at)[:10])
            trans = {code_of[mid]: no for mid, no in cmap.items() if mid in code_of}
            if trans:
                out[other.slip_id] = trans
    return out


def peers(slip: BetSlip, slips: list[BetSlip],
          cross: dict[str, dict] | None = None) -> list[BetSlip]:
    """同一盘面上的其它实购票：竞彩＝同下单日，足彩＝同期号（任九与胜负彩互为同伴）；
    `cross` 里有翻译表的跨渠道票也算同伴。"""
    out = []
    for other in slips:
        if other.slip_id == slip.slip_id or not other.purchased:
            continue
        if slip.channel == "jczq":
            same = other.channel == "jczq" and str(other.placed_at)[:10] == str(slip.placed_at)[:10]
        else:
            same = other.channel in ZUCAI_CHANNELS and other.issue == slip.issue
        if same or (cross and other.slip_id in cross):
            out.append(other)
    return out


def _naked(leg: SlipLeg) -> tuple | None:
    if len(leg.selections) != 1:
        return None
    return (leg.key, leg.market, leg.line, FACE_OF_SELECTION.get(str(leg.selections[0]),
                                                                 str(leg.selections[0])))


def shared_naked_legs(slip: BetSlip, others: list[BetSlip],
                      cross: dict[str, dict] | None = None) -> list[dict]:
    """本票的单选腿里，哪些在别的票上也是同一个单选；跨渠道票的 key 先按翻译表换算。"""
    index: dict[tuple, list[str]] = {}
    for other in others:
        trans = (cross or {}).get(other.slip_id)
        for leg in other.legs:
            key = _naked(leg)
            if key is None:
                continue
            if trans is not None:
                if leg.key not in trans:
                    continue
                key = (trans[leg.key], *key[1:])
            index.setdefault(key, []).append(other.slip_id)
    shared = []
    for leg in slip.legs:
        key = _naked(leg)
        if key is None or key not in index:
            continue
        face = key[3]
        p_face = None
        if leg.fair and leg.market == "had":
            p_face = leg.fair.get(FACE_OF.get(face, face))
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


DEVIATION_REASONS = ("fact_self_judged", "price_instinct", "stake_allocation",
                     "structure_preference", "other")
"""人相对机器初稿的偏离理由（2026-10-02）：自判事实 / 价格直觉 / 资金分配 / 结构偏好 / 其他。
账房按理由结账——定位转向后人是下注者，人的判断才是要被测量的东西。"""


def draft_faces_for(slip: BetSlip, data_dir: Path) -> dict[str, str]:
    """足彩：`<期>-draft.json` 里同渠道「初稿」的票面；竞彩不出初稿 → {}。"""
    if slip.channel not in ZUCAI_CHANNELS or not slip.issue:
        return {}
    doc = read_json(Path(data_dir) / "zucai" / f"{slip.issue}-draft.json", {}) or {}
    for cand in doc.get("candidates") or []:
        if (cand.get("label") == "初稿" and cand.get("channel") == slip.channel
                and cand.get("faces")):
            return {str(k): str(v) for k, v in cand["faces"].items()}
    return {}


def vs_draft(slip: BetSlip, draft: dict[str, str]) -> dict:
    """票面 vs 初稿：同 / 加场 / 丢场 / 放宽 / 收窄 / 换面。"""
    out: dict[str, list[str]] = {"same": [], "added": [], "dropped": [], "widened": [],
                                 "narrowed": [], "replaced": []}
    if not draft:
        return {**out, "n_diff": 0, "has_draft": False}
    mine = {str(k): "".join(sorted(v, key="310".index)) for k, v in slip.faces.items() if v}
    for no, faces in draft.items():
        faces = "".join(sorted(faces, key="310".index))
        if no not in mine:
            out["dropped"].append(no)
        elif mine[no] == faces:
            out["same"].append(no)
        elif set(mine[no]) > set(faces):
            out["widened"].append(no)
        elif set(mine[no]) < set(faces):
            out["narrowed"].append(no)
        else:
            out["replaced"].append(no)
    out["added"] = [no for no in mine if no not in draft]
    n_diff = sum(len(out[k]) for k in ("added", "dropped", "widened", "narrowed", "replaced"))
    return {**out, "n_diff": n_diff, "has_draft": True}


def diagnose(slip: BetSlip, others: list[BetSlip], prescription: dict[str, str],
             cross: dict[str, dict] | None = None, draft: dict[str, str] | None = None) -> dict:
    shared = shared_naked_legs(slip, others, cross)
    joint = joint_death(shared)
    narrow = narrowing(slip, prescription)
    against_draft = vs_draft(slip, draft or {})
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
    if against_draft["has_draft"]:
        if against_draft["n_diff"]:
            parts = [f"{k} {','.join(v)}" for k, v in (("加场", against_draft["added"]),
                                                          ("丢场", against_draft["dropped"]),
                                                          ("放宽", against_draft["widened"]),
                                                          ("收窄", against_draft["narrowed"]),
                                                          ("换面", against_draft["replaced"])) if v]
            lines.append(f"对照初稿：{against_draft['n_diff']} 处差异（{'；'.join(parts)}）"
                         + (f"；理由 {slip.deviation}" if slip.deviation else
                            "；⚠️偏离初稿未登记理由（--deviation + --prediction）"))
            if slip.deviation and not slip.prediction:
                lines.append("⚠️偏离理由没有附可证伪预测（--prediction）")
        else:
            lines.append("对照初稿：与机器初稿一致")
    if not lines:
        lines.append("诊断：无共享裸单；票面未比处方窄")
    return {"shared_naked": shared, "joint_death": joint, "narrowing": narrow,
            "vs_draft": against_draft, "lines": lines}
