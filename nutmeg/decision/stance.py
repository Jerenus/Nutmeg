"""研究表态块：校验与拨动算术（设计 2026-09-23-research-stance-contract）。

判断由分析员出（押哪个面、给什么证据），判据入代码（区间、归零、上限、T12）。
⛔本模块不读市场之外的任何东西，不推荐面。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

FACES = ("3", "1", "0")
FACE_KEY = {"3": "home", "1": "draw", "0": "away"}
STRUCTURES = ("single", "double", "full")
WHY = ("none", "tilt_evidence", "structure")
TIER_PP = {"official": (4, 8), "confirmed_structural": (3, 6), "inferred": (0, 2), "will": (0, 2)}
"""RULEBOOK l-权重表：官宣 4–8 / 确证结构 3–6 / 推断 0–2 / 战意 0–2（只许朝平）。"""
TILT_KIND_LEXICON = frozenset({
    "absence_official", "suspension", "goalkeeper_change", "anchor_integrity_fail",
    "lineup_confirmed", "venue_anomaly", "precedent_carrier", "rotation_confirmed",
    "schedule_congestion", "motivation_dead_rubber",
})
ZERO_BELOW_PP = 5
CAP_WITH_OFFICIAL_PP = 15
CAP_WITHOUT_OFFICIAL_PP = 10
MIN_FALSIFIER_CHARS = 8
_BJ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class StanceIssue:
    level: str
    field: str
    message: str


@dataclass(frozen=True)
class TiltResult:
    belief: dict
    applied_pp: int
    zeroed: bool
    reason: str
    tiers: list[str]


def stance_faces(stance: dict) -> str:
    structure = stance.get("structure")
    if structure == "full":
        return "310"
    if structure == "single":
        return str(stance.get("face"))
    chosen = {str(stance.get("face")), str(stance.get("cover"))}
    return "".join(f for f in FACES if f in chosen)


def _dead_faces(death_three_proofs: dict | None) -> set[str]:
    dead = set()
    for key, proofs in (death_three_proofs or {}).items():
        if isinstance(proofs, dict) and str(proofs.get("verdict", "alive")).lower() == "dead":
            face = {v: k for k, v in FACE_KEY.items()}.get(key, key)
            dead.add(str(face))
    return dead


def _parse(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_BJ)


def _add_error(issues: list[StanceIssue], field: str, msg: str) -> None:
    issues.append(StanceIssue("ERROR", field, msg))


def validate_stance(stance, *, confidence, death_three_proofs) -> tuple[dict, list[StanceIssue]]:
    issues: list[StanceIssue] = []
    if not isinstance(stance, dict):
        _add_error(issues, "stance", "缺 stance 表态块")
        return {}, issues
    face, structure, cover = str(stance.get("face")), stance.get("structure"), stance.get("cover")
    if face not in FACES:
        _add_error(issues, "face", f"face `{face}` 不是 3/1/0")
    if structure not in STRUCTURES:
        _add_error(issues, "structure", f"structure `{structure}` 不是 single/double/full")
    if structure == "double":
        if face not in FACES or str(cover) not in FACES or str(cover) == face:
            _add_error(issues, "cover", f"double 必须给一个不同于 face 的 cover，实得 `{cover}`")
    try:
        conf = int(stance.get("confidence"))
    except (TypeError, ValueError):
        conf = None
    if conf is None or not 1 <= conf <= 5:
        _add_error(issues, "confidence", "stance.confidence 缺失或不在 1-5")
    elif confidence is not None and int(confidence) != conf:
        _add_error(
            issues, "confidence",
            f"stance.confidence {conf} 与顶层 confidence {confidence} 不一致",
        )
    falsifier = str(stance.get("falsifier") or "").strip()
    if len(falsifier) < MIN_FALSIFIER_CHARS:
        _add_error(
            issues, "falsifier",
            f"falsifier 少于 {MIN_FALSIFIER_CHARS} 字（要一句赛后可核验的作废条件）",
        )
    why = stance.get("why_not_market")
    tilt = stance.get("tilt")
    dead = _dead_faces(death_three_proofs)
    if why not in WHY:
        _add_error(
            issues, "why_not_market",
            f"why_not_market `{why}` 不是 none/tilt_evidence/structure",
        )
    if why == "tilt_evidence" and not tilt:
        _add_error(issues, "tilt", "why_not_market=tilt_evidence 但没有 tilt")
    if why != "tilt_evidence" and tilt:
        _add_error(issues, "tilt", "给了 tilt 就必须 why_not_market=tilt_evidence")
    if why == "structure" and not dead:
        _add_error(issues, "why_not_market", "why_not_market=structure 但没有面被判死（三证）")
    faces = stance_faces(stance) if face in FACES and structure in STRUCTURES else ""
    if faces and dead & set(faces):
        _add_error(
            issues, "structure",
            f"表态面集合 `{faces}` 含已判死的面 {sorted(dead & set(faces))}",
        )
    tiers: list[str] = []
    if isinstance(tilt, dict):
        tface = str(tilt.get("face"))
        if tface not in FACES:
            _add_error(issues, "tilt.face", f"tilt.face `{tface}` 不是 3/1/0")
        evidence = tilt.get("evidence") or []
        if not evidence:
            _add_error(issues, "tilt.evidence", "tilt 至少要一条证据")
        for i, e in enumerate(evidence):
            tier, kind = e.get("tier"), e.get("kind")
            if tier not in TIER_PP:
                _add_error(issues, f"tilt.evidence.{i}", f"tier `{tier}` 不在 {sorted(TIER_PP)}")
                continue
            lo, hi = TIER_PP[tier]
            try:
                pp = int(e.get("pp"))
            except (TypeError, ValueError):
                pp = -1
            if not lo <= pp <= hi:
                _add_error(issues, f"tilt.evidence.{i}", f"{tier} 的 pp {pp} 不在 [{lo},{hi}]")
            if tier == "will" and tface != "1":
                _add_error(issues, f"tilt.evidence.{i}", "will（战意）只许朝平，tilt.face 必须是 1")
            if kind not in TILT_KIND_LEXICON:
                _add_error(issues, f"tilt.evidence.{i}", f"kind `{kind}` 不在词典")
            if _parse(e.get("captured_at")) is None:
                _add_error(issues, f"tilt.evidence.{i}", "captured_at 不是合法时间")
            tiers.append(str(tier))
    alt = stance.get("alt_face")
    if alt not in (None, *FACES):
        _add_error(issues, "alt_face", f"alt_face `{alt}` 不是 3/1/0")
    mr = stance.get("market_read")
    if mr not in (None, "agree", "overpriced", "underpriced"):
        _add_error(issues, "market_read", f"market_read `{mr}` 不合法")
    norm = {
        "face": face, "structure": structure, "cover": str(cover) if cover is not None else None,
        "confidence": conf, "falsifier": falsifier, "why_not_market": why,
        "tilt": tilt if isinstance(tilt, dict) else None, "alt_face": alt, "market_read": mr,
        "faces": faces, "tiers": tiers,
    }
    return norm, issues


def apply_tilt(prior: dict, tilt: dict | None, *, kickoff: str | None = None) -> TiltResult:
    prior = {k: float(prior[k]) for k in ("home", "draw", "away")}
    if not tilt:
        return TiltResult(dict(prior), 0, True, "无 tilt：跟市场", [])
    kick = _parse(kickoff) if kickoff else None
    kept, dropped, tiers = [], 0, []
    for e in tilt.get("evidence") or []:
        at = _parse(e.get("captured_at"))
        if kick and at and at >= kick:
            dropped += 1
            continue
        kept.append(e)
        tiers.append(str(e.get("tier")))
    net = sum(int(e.get("pp") or 0) for e in kept)
    if net < ZERO_BELOW_PP:
        why = f"净偏移 {net}pp <{ZERO_BELOW_PP}pp 归零跟市场" + (
            f"（{dropped} 条证据在开球后，作废）" if dropped else ""
        )
        return TiltResult(dict(prior), 0, True, why, tiers)
    cap = CAP_WITH_OFFICIAL_PP if "official" in tiers else CAP_WITHOUT_OFFICIAL_PP
    applied = min(net, cap)
    key = FACE_KEY[str(tilt["face"])]
    target = min(0.98, max(0.01, prior[key] + applied / 100))
    rest = [k for k in prior if k != key]
    rest_mass = sum(prior[k] for k in rest) or 1.0
    belief = {k: (1 - target) * prior[k] / rest_mass for k in rest}
    belief[key] = target
    reason = f"拨 {applied}pp 向 {tilt['face']}" + (
        f"（上限 {cap}pp 截断自 {net}pp）" if applied < net else ""
    )
    return TiltResult(belief, applied, False, reason, tiers)
