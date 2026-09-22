"""三种默认表达（裸单 / 模态双选 / 全包）各自会触发哪些审计码。

纯算术，不推荐、不排序（设计 §6.1）。
"""
from __future__ import annotations

from nutmeg.decision.legs_audit import audit_legs, has_blocking, legs_from_dict

FACE_OF = {"home": "3", "draw": "1", "away": "0"}
_ORDER = ("3", "1", "0")


def default_expressions(fair: dict) -> dict[str, str]:
    ranked = sorted(("home", "draw", "away"), key=lambda k: -float(fair.get(k, 0)))
    naked = FACE_OF[ranked[0]]
    pair = {FACE_OF[ranked[0]], FACE_OF[ranked[1]]}
    return {"naked": naked, "double": "".join(f for f in _ORDER if f in pair), "full": "310"}


def _leg_payload(card: dict, faces: str) -> dict:
    labels = card.get("labels") or {}
    team_tags = labels.get("team_tags") or []
    if isinstance(team_tags, list):  # 卡片里是 [[side, tag], …]；Leg 要 {side: [tag]}
        grouped: dict[str, list] = {"home": [], "away": []}
        for item in team_tags:
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in grouped:
                grouped[item[0]].append(item[1])
        team_tags = grouped
    return {
        "name": card.get("name", ""), "faces": faces, "fair": card["market"]["fair"],
        "confidence": labels.get("confidence") or 0,
        "directional_flags": labels.get("directional_flags") or [],
        "nondirectional_flags": labels.get("nondirectional_flags") or [],
        "anchor_integrity": labels.get("anchor_integrity") or "unknown",
        "precedents": labels.get("precedents") or [],
        "crash_markers": labels.get("crash_markers") or [],
        "tracking_tags": labels.get("tracking_tags") or [], "team_tags": team_tags,
        "license_questions": labels.get("license_questions"),
    }


def audit_defaults(card: dict) -> dict:
    fair = (card.get("market") or {}).get("fair")
    if not fair:
        return {"error": "fair 缺失，无法展开默认表达"}
    out: dict = {}
    try:
        for label, faces in default_expressions(fair).items():
            legs = legs_from_dict({"issue": card.get("code", ""),
                                   "legs": {"1": _leg_payload(card, faces)}})
            findings = audit_legs(legs)
            out[label] = {
                "faces": faces,
                "blocking": has_blocking(findings),
                "findings": [{"level": f.level, "code": f.code, "message": f.message}
                             for f in findings],
            }
    except Exception as exc:  # noqa: BLE001 — 审计列缺席不塌卡片
        return {"error": f"audit 失败: {exc!r}"[:300]}
    return out
