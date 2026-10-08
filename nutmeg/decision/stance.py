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
TIER_PP = {"official": (4, 8), "confirmed_structural": (3, 6), "inferred": (0, 2), "will": (0, 2),
           "state": (0, 3)}
"""RULEBOOK l-权重表：官宣 4–8 / 确证结构 3–6 / 推断 0–2 / 战意 0–2（只许朝平）/ 本场状态 0–3。

`state` 由 strength-v2（2026-09-26 Jun 批准）加入：判断目标改为两队本场强度对比，
状态不再一律 0pp，但只许小幅（≤3pp），并须写明是本场的状态而非长期战绩。"""
TILT_KIND_LEXICON = frozenset({
    "absence_official", "suspension", "goalkeeper_change", "anchor_integrity_fail",
    "lineup_confirmed", "venue_anomaly", "precedent_carrier", "rotation_confirmed",
    "schedule_congestion", "motivation_dead_rubber",
    # strength-v2：强弱天平的事件类别
    "style_matchup", "underdog_path", "form_state", "travel_fatigue", "coach_debut",
    "pitch_condition", "squad_depth", "priced_drift",
})
ZERO_BELOW_PP = 0
"""strength-v2 起不再归零：<5pp 的真实利好利空如实表达（旧值 5，2026-09-26 退休）。
归零让深研每期都『同意市场』，belief≡prior，判断力从未被表达也无从测量。"""
CAP_WITH_OFFICIAL_PP = 15
CAP_WITHOUT_OFFICIAL_PP = 10
KIND_PP_CAP = {"form_state": 1}
ANCHOR_TIERS = frozenset({"official", "confirmed_structural"})
"""拨动至少要一条官宣或确证结构级证据做锚，否则归零跟市场（Jun 2026-09-30）。
09-28/09-29 两天：研究表态面 8/8 对，但全部拨动（状态/推断级）净负，市场 Brier 最好；
F9 n=25 −0.74pp CI 含 0。结构判断有价值，程度判断没有——把预算留给结构。"""
"""单场状态 / 同组交叉（form_state）每条最多计 1pp（Jun 2026-09-30）。
出生事故：09-28 三处同组交叉拨动（004/005/足彩03）全反，09-29 012 冰岛再反——n=1 的 xG
对比一场能挪 3pp。多面位移的峰值也不得超过证据预算（Σ 计入 pp），否则 shift 是自由写的数字。"""


def _evidence_budget(evidence: list[dict]) -> int:
    return sum(
        min(int(e.get("pp") or 0), KIND_PP_CAP.get(str(e.get("kind")), int(e.get("pp") or 0)))
        for e in evidence
    )
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


def _validate_shift(shift, issues: list[StanceIssue]) -> str:
    """多面位移 {"3":pp,"1":pp,"0":pp}：整数、和为 0、不全为 0。返回获益最多的面。"""
    if not isinstance(shift, dict) or not shift or not set(map(str, shift)) <= set(FACES):
        _add_error(issues, "tilt.shift", f"shift 必须是 {{3/1/0: pp}}，实得 `{shift}`")
        return ""
    try:
        values = {str(k): int(v) for k, v in shift.items()}
    except (TypeError, ValueError):
        _add_error(issues, "tilt.shift", "shift 的 pp 必须是整数")
        return ""
    if sum(values.values()) != 0:
        _add_error(issues, "tilt.shift", f"shift 各面之和必须为 0，实得 {sum(values.values())}")
    if not any(values.values()):
        _add_error(issues, "tilt.shift", "shift 全为 0——跟市场请用 tilt=null")
        return ""
    return max(values, key=values.get)


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
    # why_not_market 是 tilt 与三证的派生标签：自相矛盾时按事实改标签并留痕，
    # 不整份驳回（2026-09-26 周六006/010/015 各丢一份深研）。
    normalized: list[str] = []
    if why == "tilt_evidence" and not tilt:
        normalized.append("why_not_market tilt_evidence→none（没有 tilt）")
        why = "none"
    if why in ("none", "structure") and tilt:
        normalized.append(f"why_not_market {why}→tilt_evidence（给了 tilt）")
        why = "tilt_evidence"
    if why == "structure" and not dead:
        normalized.append(
            "why_not_market structure→none（没有面被判死，strength-v2 下三证不再是前提）"
        )
        why = "none"
    faces = stance_faces(stance) if face in FACES and structure in STRUCTURES else ""
    if faces and dead & set(faces):
        _add_error(
            issues, "structure",
            f"表态面集合 `{faces}` 含已判死的面 {sorted(dead & set(faces))}",
        )
    tiers: list[str] = []
    if isinstance(tilt, dict):
        shift = tilt.get("shift")
        if shift is not None:
            tface = _validate_shift(shift, issues)
        else:
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
            if pp < 0:
                _add_error(issues, f"tilt.evidence.{i}", "pp 必须是非负整数")
            elif pp > hi:
                # 格式问题不该废掉整份深研（周一001、26134-14 各因此被拒两次，2026-09-30）
                normalized.append(f"tilt.evidence.{i} {tier} pp {pp}→{hi}（封顶到 [{lo},{hi}]）")
                e["pp"] = pp = hi
            elif pp < lo:
                normalized.append(
                    f"tilt.evidence.{i} {tier} pp {pp} 低于该层下限 {lo}，按写入值计（不拒收）"
                )
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
        "faces": faces, "tiers": tiers, "normalized": normalized,
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
    if kept and not (set(tiers) & ANCHOR_TIERS):
        why = "无官宣/确证结构级证据做锚：拨动归零跟市场（2026-09-30）" + (
            f"（{dropped} 条证据在开球后，作废）" if dropped else ""
        )
        return TiltResult(dict(prior), 0, True, why, tiers)
    net = _evidence_budget(kept)
    if tilt.get("shift") is not None:
        return _apply_shift(prior, tilt["shift"], kept=kept, dropped=dropped, tiers=tiers)
    if net <= ZERO_BELOW_PP:
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


def _apply_shift(prior: dict, shift: dict, *, kept: list, dropped: int,
                 tiers: list[str]) -> TiltResult:
    """strength-v2 多面位移：belief = prior + shift/100；单面幅度超上限则整体等比缩放。"""
    if not kept:
        why = "无有效证据，归零跟市场" + (f"（{dropped} 条证据在开球后，作废）" if dropped else "")
        return TiltResult(dict(prior), 0, True, why, tiers)
    values = {FACE_KEY[str(k)]: int(v) for k, v in shift.items()}
    peak = max(abs(v) for v in values.values())
    cap = CAP_WITH_OFFICIAL_PP if "official" in tiers else CAP_WITHOUT_OFFICIAL_PP
    budget = _evidence_budget(kept)
    limit = min(cap, budget)
    scale = min(1.0, limit / peak) if peak else 1.0
    raw = {k: min(0.98, max(0.01, prior[k] + scale * values.get(k, 0) / 100)) for k in prior}
    total = sum(raw.values())
    belief = {k: v / total for k, v in raw.items()}
    applied = round(peak * scale)
    if scale < 1 and budget < cap:
        note = f"（证据预算 {budget}pp 截断自 {peak}pp）"
    elif scale < 1:
        note = f"（单面上限 {cap}pp 截断自 {peak}pp）"
    else:
        note = ""
    reason = "多面位移 " + " ".join(
        f"{d}{scale * values.get(FACE_KEY[d], 0):+.1f}" for d in FACES
    ) + note
    return TiltResult(belief, applied, False, reason, tiers)


def research_belief(prior: dict, tilt: dict | None, *, kickoff: str | None = None,
                    alive=None) -> tuple[dict, TiltResult]:
    """研究表态 → belief：竞彩 / 足彩 Read、信号面板、改判账共用的唯一实现（2026-10-08 B2）。

    tilt 走 l 条拨动算术（`apply_tilt`）；归零即跟市场，belief 原样是 prior。
    `alive`（home/draw/away 的活面集合）给出时，三证判死的面优先于拨动：拨动结果（或 prior）
    上把非活面清零、在活面上归一。`alive=None` 不按面状态处理——足彩只在研究真判了死面时
    才传（全活时归一只会改浮点尾数，让内容没变的 Read 被当成「变了」重交本体）。
    """
    result = apply_tilt(prior, tilt, kickoff=kickoff)
    belief = dict(prior) if result.zeroed else dict(result.belief)
    if alive is None:
        return belief, result
    kept = {face: (float(belief[face]) if face in alive else 0.0)
            for face in ("home", "draw", "away")}
    mass = sum(kept.values())
    if mass <= 0:
        raise ValueError("没有可归一的活面")
    return {face: value / mass for face, value in kept.items()}, result
