"""判断 rubric r1 的逐项因子行（T13 因子注册表的 row_builder，2026-10-02）。

每个带效应的 rubric 项一个因子：行 = {factor: 项是否成立(0/1), face_hit: 效应面是否开出,
fair: 效应面的市场价, provably_prospective}。效应面＝该项"认为更可能"的那一面：down:home
的效应面是"非主胜"（取 draw+away 的合并面），up:draw 的效应面是平。
`face_hit_rate_resid_pp`（命中 − fair）由 noise_floor.permutation_floor 算；
factor=0 的对照行＝该项被明确答"否/none"的场（弃权的场不进行）。

权重永远不在这里写：propose 只提案，上限只许人经 `rsi deploy` 往下调或退役。
"""
from __future__ import annotations

from collections.abc import Callable

from nutmeg.decision.rubric_items import DIRECTIONAL_ITEMS, ITEMS, UNKNOWN

_FACE = {"home": "3", "draw": "1", "away": "0"}
EFFECT_THRESHOLD = 0.5


def _effect_faces(item_id: str, answer: str, anchor: str | None) -> list[str] | None:
    """项成立时它押的面集合（赛果码 3/1/0）；算不出（无锚）→ None。"""
    item = ITEMS[item_id]
    kind, _, target = item.effect.partition(":")
    target = target.split(":")[0]
    if target == "side":
        sides = ["home", "away"] if answer == "both" else [answer]
        hurt = {_FACE[s] for s in sides if s in _FACE}
    elif target in ("home", "away"):
        hurt = {_FACE[target]}
    elif target in ("anchor", "underdog"):
        if anchor not in ("home", "away"):
            return None
        side = anchor if target == "anchor" else ("away" if anchor == "home" else "home")
        hurt = {_FACE[side]}
    elif target == "draw":
        return ["1"]
    else:
        return None
    if kind == "down":
        return sorted({"3", "1", "0"} - hurt)
    return sorted(hurt)


def _answered(row_items: dict, item_id: str) -> tuple[bool | None, str]:
    """→ (成立?, 答案)；弃权/没答 → (None, '')。"""
    rec = (row_items or {}).get(item_id)
    if not isinstance(rec, dict):
        return None, ""
    answer, p = rec.get("answer"), rec.get("p")
    item = ITEMS[item_id]
    try:
        p = float(p) if p is not None else None
    except (TypeError, ValueError):
        p = None
    if item.type == "noul":
        if answer not in ("yes", "no"):
            return None, ""
        if item.effect.endswith(":no"):
            return answer == "no", answer
        return answer == "yes" and (p is None or p >= EFFECT_THRESHOLD), answer
    if answer in (None, UNKNOWN):
        return None, ""
    return (answer in item.effect_options) and (p is None or p >= EFFECT_THRESHOLD), str(answer)


def _rows_for(item_id: str, *, reader: str = "rubric") -> Callable[[list[dict]], list[dict]]:
    def build(rows: list[dict]) -> list[dict]:
        out: list[dict] = []
        for row in rows:
            labels = row.get("labels") or {}
            src = labels.get(reader)
            if reader == "rubric_b":
                src = (src or {}).get("items") if isinstance(src, dict) else None
            if not isinstance(src, dict) or not row.get("fair") or row.get("actual") is None:
                continue
            active, answer = _answered(src, item_id)
            if active is None:
                continue
            anchor_rec = src.get("S_anchor_side") or {}
            anchor = anchor_rec.get("answer") if isinstance(anchor_rec, dict) else None
            faces = _effect_faces(item_id, answer or "home", anchor)
            if not faces:
                continue
            fair = row["fair"]
            coverage = sum(float(fair[k]) for k, code in _FACE.items() if code in faces)
            out.append({
                "factor": int(bool(active)),
                "face_hit": int(str(row["actual"]) in faces),
                "fair": coverage,
                "provably_prospective": row.get("provably_prospective"),
                "key": row.get("key"),
            })
        return out
    build.__name__ = f"rows_{item_id}"
    return build


_FACTORS: dict[str, tuple[Callable[[list[dict]], list[dict]], str]] = {}
for _item_id in DIRECTIONAL_ITEMS:
    _item = ITEMS[_item_id]
    _FACTORS[f"rubric_{_item_id}"] = (
        _rows_for(_item_id),
        f"reader A; item active (p>=0.5 / effect option) = 1, explicit no/none = 0; "
        f"outcome = effect face set of '{_item.effect}' opened",
    )
    globals()[f"rows_{_item_id}"] = _FACTORS[f"rubric_{_item_id}"][0]


def factor_entries() -> list[dict]:
    """给 `experiments/factors.json` 的登记条目（layer=probability，权重 0，上限只许往下）。"""
    out = []
    for item_id in DIRECTIONAL_ITEMS:
        item = ITEMS[item_id]
        out.append({
            "factor_id": f"rubric_{item_id}",
            "rule_codes": [],
            "rule_name": f"rubric r1 · {item_id}（{item.effect}，上限 {item.cap_pp}pp）",
            "layer": "probability",
            "claim": f"{item.text}——成立时效应面比市场价更容易开出。",
            "current_weight_pp": 0.0,
            "weight_band": [-15.0, 15.0],
            "row_builder": f"experiments.rubric_rows:rows_{item_id}",
            "last_measured": None,
            "note": "判断 rubric r1（2026-10-02）：pp = 上限 × 概率；propose_zero → 上限退役；"
                    "propose_change 只许把上限往下截。",
        })
    return out
