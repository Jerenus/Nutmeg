"""判断 rubric（r1 2026-10-02 / r2 2026-10-19 上限退役）：校验、强制弃权、派生 tilt
（设计 2026-10-02-rubric-judgment-contract）。

- 判断归 LLM：每项给"这件事成立的概率"与来源；
- 权重归结账：pp = 项目上限 × 概率，上限只从 RSI 结账往下调；
- 协议级聚合：事实层无成立项 → 预算 0（无锚归零）；`S_anchor_side=none` → 全部归零；
  `M_facts_priced` → 事实层 pp 减半；总峰值 ≤ 15pp；
- 派生出的 `stance.tilt`（多面 shift + 逐项 evidence）走现有 `validate_stance/apply_tilt`，
  下游（C19/C8/F14/signals/面板）接口不变。
⛔本模块不读市场之外的任何东西，不推荐面。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.bj_time import BJ, parse_bj
from nutmeg.decision.faces import FACE_OF
from nutmeg.decision.rubric_items import (
    EFFECT_ITEMS,
    FACT_ITEMS,
    ITEMS,
    MAX_ABS_SHIFT_PP,
    RUBRIC_VERSION,
    SOURCE_TIERS,
    SUPPORTED_VERSIONS,
    UNKNOWN,
    cap_at,
    directional_items,
)

FACE_OF_SIDE = {"home": "3", "away": "0"}
OTHER_SIDE = {"home": "away", "away": "home"}
EFFECT_THRESHOLD = 0.5
"""p < 0.5 视为"不成立"，不计 pp（弃权的另一种写法）。"""


@dataclass(frozen=True)
class RubricIssue:
    level: str
    field: str
    message: str


def _p(value) -> float | None:
    if value is None:
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    return p if 0.0 <= p <= 1.0 else None


def validate_rubric(rubric, *, kickoff: str | None = None) -> tuple[dict, list[RubricIssue]]:
    """→ (norm, issues)。norm = {version, items: {id: {answer, p, source, captured_at, note,
    abstain, coerced}}, belief, coerced: [..]}。ERROR 只给结构性问题（非法 id/选项/概率域）；
    "答是但无来源"不是 ERROR，是**强制弃权**并留痕（反"把没说的当成说了"）。"""
    issues: list[RubricIssue] = []
    if not isinstance(rubric, dict):
        issues.append(RubricIssue("ERROR", "rubric", "缺 rubric 块"))
        return {}, issues
    version = str(rubric.get("version") or RUBRIC_VERSION)
    if version not in SUPPORTED_VERSIONS:
        issues.append(RubricIssue("ERROR", "rubric.version",
                                  f"版本 {version} 不在 {SUPPORTED_VERSIONS}"))
    raw_items = rubric.get("items")
    if not isinstance(raw_items, dict):
        issues.append(RubricIssue("ERROR", "rubric.items", "items 必须是 {id: 答案}"))
        return {}, issues
    kick = parse_bj(kickoff) if kickoff else None
    norm_items: dict[str, dict] = {}
    coerced: list[str] = []
    for item_id, raw in raw_items.items():
        item = ITEMS.get(str(item_id))
        if item is None:
            issues.append(RubricIssue("ERROR", f"rubric.items.{item_id}", "不在问题表里"))
            continue
        if not isinstance(raw, dict):
            raw = {"p": raw} if item.type == "noul" else {"answer": raw}
        answer = raw.get("answer")
        p = _p(raw.get("p"))
        source = str(raw.get("source") or "").strip()
        captured_at = raw.get("captured_at")
        note = str(raw.get("note") or "")[:200]
        source_tier = str(raw.get("source_tier") or UNKNOWN)
        if source_tier not in SOURCE_TIERS:
            source_tier = UNKNOWN
        abstain = False
        if item.type == "noul":
            if raw.get("p") is not None and p is None:
                issues.append(RubricIssue("ERROR", f"rubric.items.{item_id}.p", "p 必须在 [0,1]"))
                continue
            abstain = p is None
            answer = None if abstain else ("yes" if p >= EFFECT_THRESHOLD else "no")
        elif item.type == "choice":
            answer = str(answer) if answer is not None else UNKNOWN
            if answer not in item.options:
                issues.append(RubricIssue("ERROR", f"rubric.items.{item_id}.answer",
                                          f"选项 `{answer}` 不在 {item.options}"))
                continue
            abstain = answer == UNKNOWN
            if p is None and not abstain:
                p = 1.0
        else:
            issues.append(RubricIssue("ERROR", f"rubric.items.{item_id}", f"未知类型 {item.type}"))
            continue
        active = (not abstain) and (
            (item.type == "noul" and answer == "yes")
            or (item.type == "choice" and answer in item.effect_options)
        )
        why = ""
        if active and item.source_required:
            at = parse_bj(captured_at)
            if not source:
                why = "答是但无来源"
            elif at is None:
                why = "答是但 captured_at 不是合法时间"
            elif kick and at >= kick:
                why = "来源采集时间晚于开球（T12）"
        if why:
            coerced.append(f"{item_id}: {why} → 弃权")
            abstain, answer, p = True, None if item.type == "noul" else UNKNOWN, None
        norm_items[item.id] = {
            "answer": answer, "p": round(p, 3) if p is not None else None, "source": source,
            "source_tier": source_tier, "captured_at": captured_at, "note": note,
            "abstain": abstain, "coerced": bool(why),
        }
    belief = rubric.get("belief")
    norm_belief = None
    if belief is not None:
        vals: dict[str, float] = {}
        if isinstance(belief, dict):
            try:
                vals = {k: float(belief[k]) for k in ("3", "1", "0")}
            except (KeyError, TypeError, ValueError):
                vals = {}
        total = sum(vals.values())
        if vals and 0.98 <= total <= 1.02 and all(0 <= v <= 1 for v in vals.values()):
            norm_belief = {k: round(v / total, 4) for k, v in vals.items()}
        else:
            issues.append(RubricIssue("ERROR", "rubric.belief", "belief 必须是 3/1/0 的概率分布"))
    for item_id, item in ITEMS.items():
        norm_items.setdefault(item_id, {"answer": None if item.type == "noul" else UNKNOWN,
                                        "p": None, "source": "", "captured_at": None, "note": "",
                                        "abstain": True, "coerced": False})
    norm = {"version": version, "items": norm_items, "belief": norm_belief,
            "coerced": coerced}
    return norm, issues


def tolerate(items) -> dict:
    """一个不合法的选项不该废掉整份作答（读者 B 与分析员同用，2026-10-02）——
    不在表里的项丢弃；choice 答案不在选项里 → unknown（弃权）；noul 的 p 不在 [0,1] → null。
    留痕在 `_tolerated`，报表可数。"""
    out: dict = {}
    if not isinstance(items, dict):
        return out
    for item_id, raw in items.items():
        item = ITEMS.get(str(item_id))
        if item is None:
            continue
        row = dict(raw) if isinstance(raw, dict) else (
            {"p": raw} if item.type == "noul" else {"answer": raw})
        if item.type == "choice":
            if str(row.get("answer")) not in item.options:
                fallback = "unknown" if "unknown" in item.options else item.options[-1]
                row["_tolerated"] = f"answer {row.get('answer')!r} → {fallback}"
                row["answer"] = fallback
        else:
            try:
                p = float(row["p"]) if row.get("p") is not None else None
            except (TypeError, ValueError):
                p = None
            if p is not None and not 0.0 <= p <= 1.0:
                row["_tolerated"] = f"p {row['p']!r} → null"
                p = None
            row["p"] = p
        out[str(item_id)] = row
    return out


def tolerate_belief(belief) -> dict | None:
    """整体概率不是合法的 3/1/0 分布（缺键、负数、和差太远）→ 丢掉，不废整份作答。"""
    if not isinstance(belief, dict):
        return None
    try:
        vals = {k: float(belief[k]) for k in ("3", "1", "0")}
    except (KeyError, TypeError, ValueError):
        return None
    total = sum(vals.values())
    if total <= 0 or any(v < 0 for v in vals.values()) or not 0.9 <= total <= 1.1:
        return None
    return {k: v / total for k, v in vals.items()}


def soften(rubric) -> tuple[dict, list[str]]:
    """分析员的 rubric 软化：缺失 → 全部弃权（跟市场）；不合法选项/概率/整体分布 → 弃权或丢弃；
    版本不认识 → 按当前版本读。→ (可校验的 rubric, 留痕)。深研永不因 rubric 被拒收——
    拒收会烧 40 场/日的预算并在 R0/R1 覆盖上留缺口（Jun 2026-10-02「保持池子 rsi 的工作」）。"""
    notes: list[str] = []
    if not isinstance(rubric, dict):
        notes.append("rubric 缺失 → 全部弃权（跟市场）")
        return {"version": RUBRIC_VERSION, "items": {}, "belief": None}, notes
    out = dict(rubric)
    if str(out.get("version") or RUBRIC_VERSION) not in SUPPORTED_VERSIONS:
        notes.append(f"version {out.get('version')!r} → {RUBRIC_VERSION}")
        out["version"] = RUBRIC_VERSION
    out["items"] = tolerate(out.get("items"))
    notes += [f"{k}: {v['_tolerated']}" for k, v in out["items"].items() if v.get("_tolerated")]
    if out.get("belief") is not None:
        belief = tolerate_belief(out.get("belief"))
        if belief is None:
            notes.append("belief 不是合法 3/1/0 分布 → 丢弃")
        out["belief"] = belief
    return out, notes


def _active(norm_items: dict, item_id: str) -> tuple[bool, float, str]:
    """→ (成立?, p, 答案)。"""
    row = norm_items.get(item_id) or {}
    item = ITEMS[item_id]
    if row.get("abstain"):
        return False, 0.0, ""
    p = float(row.get("p") or 0.0)
    answer = str(row.get("answer") or "")
    if item.type == "noul":
        if item.effect.endswith(":no"):
            return answer == "no", 1.0 - p if p else 0.0, answer
        return answer == "yes" and p >= EFFECT_THRESHOLD, p, answer
    return answer in item.effect_options and p >= EFFECT_THRESHOLD, p, answer


def _effect_faces(effect: str, answer: str, anchor: str | None) -> list[tuple[str, int]]:
    """效应 → [(面, 符号)]：符号 −1 = 该面减，+1 = 该面加。"""
    kind, _, target = effect.partition(":")
    target = target.split(":")[0]
    sign = -1 if kind == "down" else 1
    if target == "side":
        sides = ["home", "away"] if answer == "both" else [answer]
        return [(FACE_OF_SIDE[s], sign) for s in sides if s in FACE_OF_SIDE]
    if target in ("anchor", "underdog"):
        if anchor not in FACE_OF_SIDE:
            return []
        side = anchor if target == "anchor" else OTHER_SIDE[anchor]
        return [(FACE_OF_SIDE[side], sign)]
    if target in ("home", "away"):
        return [(FACE_OF_SIDE[target], sign)]
    if target == "draw":
        return [("1", sign)]
    return []


def rubric_to_tilt(norm: dict, prior: dict | None = None, *,
                   captured_at: str | None = None,
                   version: str = RUBRIC_VERSION) -> dict | None:
    """协议级聚合 → `stance.tilt`（多面 shift + 逐项 evidence）；无可用拨动 → None。

    `captured_at`：不要求来源的项（结构层）没有自己的采集时间，用研究落盘时间；
    没给就用现在（运行器落盘时会统一盖章）。`version`：按哪一版的上限聚合（r2 起 10 项上限退役）。

    事实层无成立项 → None（无锚归零，= 2026-09-30 ANCHOR_TIERS 规则）；
    `S_anchor_side=none` → None；`M_facts_priced` 成立 → 事实层 pp ×0.5；
    shift 峰值 > 15pp 整体等比缩放；pp 四舍五入为整数，evidence 的 pp 之和 ≥ 峰值
    （`_apply_shift` 的证据预算约束才不会二次截断）。
    """
    items = norm.get("items") or {}
    anchor_row = items.get("S_anchor_side") or {}
    anchor = anchor_row.get("answer") if not anchor_row.get("abstain") else None
    if anchor == "none":
        return None
    fact_active = [i for i in FACT_ITEMS if _active(items, i)[0]]
    if not fact_active:
        return None
    priced, _, _ = _active(items, "M_facts_priced")
    contributions: list[tuple[str, float, list[tuple[str, int]]]] = []
    for item_id in directional_items(version):
        active, p, answer = _active(items, item_id)
        if not active:
            continue
        item = ITEMS[item_id]
        pp = cap_at(item, version) * p
        if item.phase == "fact" and priced:
            pp *= 0.5
        faces = _effect_faces(item.effect, answer, anchor)
        if not faces or pp < 0.5:
            continue
        contributions.append((item_id, pp, faces))
    if not contributions:
        return None
    raw_shift = {"3": 0.0, "1": 0.0, "0": 0.0}
    for _item_id, pp, faces in contributions:
        for face, sign in faces:
            raw_shift[face] += sign * pp
    # 补偿面：减掉的质量按另两面的 prior 比例加回（或加上的从另两面按比例扣），和为 0
    prior = prior or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    key = FACE_OF
    shift = dict(raw_shift)
    for face, delta in raw_shift.items():
        if not delta:
            continue
        others = [f for f in shift if f != face]
        mass = sum(float(prior[key[f]]) for f in others) or 1.0
        for f in others:
            shift[f] -= delta * float(prior[key[f]]) / mass
    peak = max(abs(v) for v in shift.values())
    scale = min(1.0, MAX_ABS_SHIFT_PP / peak) if peak else 1.0
    rounded = {f: int(round(v * scale)) for f, v in shift.items()}
    drift = sum(rounded.values())
    if drift:
        top = max(rounded, key=lambda f: abs(rounded[f]))
        rounded[top] -= drift
    if not any(rounded.values()):
        return None
    evidence = []
    fallback_at = captured_at or norm.get("captured_at") or datetime.now(BJ).isoformat(
        timespec="seconds")
    for item_id, pp, _faces in contributions:
        row = items[item_id]
        item = ITEMS[item_id]
        evidence.append({"tier": item.tier, "kind": item.kind,
                         "pp": max(1, int(round(pp * scale))), "source": row.get("source") or "",
                         "captured_at": row.get("captured_at") or fallback_at, "item": item_id,
                         "answer": row.get("answer"), "p": row.get("p")})
    budget = sum(e["pp"] for e in evidence)
    peak_int = max(abs(v) for v in rounded.values())
    if budget < peak_int:                      # 让 evidence 预算盖住峰值（整数舍入造成的缺口）
        evidence[0]["pp"] += peak_int - budget
    return {"shift": rounded, "evidence": evidence, "derived_from": f"rubric:{version}",
            "expires_if": "任一成立的事实项被官方推翻（首发公布与之相反）",
            "priced_halved": bool(priced)}


def derive_stance(stance: dict | None, norm: dict, prior: dict | None = None, *,
                  captured_at: str | None = None) -> dict:
    """分析员的 `stance.tilt` 搬到 `tilt_declared`；`tilt` 由 rubric 派生；改标 why_not_market。"""
    out = dict(stance or {})
    declared = out.get("tilt")
    if declared is not None and not (isinstance(declared, dict)
                                     and declared.get("derived_from")):
        out["tilt_declared"] = declared
    tilt = rubric_to_tilt(norm, prior, captured_at=captured_at)
    out["tilt"] = tilt
    out["why_not_market"] = "tilt_evidence" if tilt else (
        "structure" if out.get("why_not_market") == "structure" else "none")
    return out


def rubric_summary(norm: dict | None, *, kappa: float | None = None) -> str:
    """面板一格：事实 x/7 · 结构 y/6 · 弃权 z · 预算 pp · κ。"""
    if not norm:
        return "—"
    items = norm.get("items") or {}
    fact = sum(1 for i in FACT_ITEMS if _active(items, i)[0])
    struct_ids = [i for i in EFFECT_ITEMS if ITEMS[i].phase == "structure"]
    struct = sum(1 for i in struct_ids if _active(items, i)[0])
    abstain = sum(1 for r in items.values() if r.get("abstain"))
    tilt = rubric_to_tilt(norm)
    peak = max(abs(v) for v in tilt["shift"].values()) if tilt else 0
    text = (f"事实{fact}/{len(FACT_ITEMS)} 结构{struct}/{len(struct_ids)} 弃权{abstain} "
            f"预算{peak}pp")
    if kappa is not None:
        text += f" κ{kappa:.2f}"
    return text
