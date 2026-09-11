"""判读 → Read/legs 结构化桥 —— 把手敲 JSON 从判读链路里拿掉。

**Why.** 26122 的 14 条 Read 与 14 条 legs（含 team_tags / flags / precedents / crash_markers）
是我在 python heredoc 里逐字段手敲的，踩了三个坑：`directional_flags` 的二元组格式、
偏离登记只认固定 rule_ids、store 的 match_id/snapshot_id 靠 fair 值反查。这些都不是判断，
是**转录**——转录出错会让审计门检查一份与判读不一致的票面，比不检查更糟。

本模块吃一份 `judgment-v1`（主循环判读的结构化产物，每场一条），吐出：
- `<issue>-reads.json`：`decision-read` 的入参（belief=prior，偏移由 judgment 显式声明）
- `<issue>-legs-base.json`：`decision-audit-legs` 的入参（处方票面 + 全部结构字段）

**判断不在这里**：每一场的动作、旗、标签、三证都必须在 judgment 里写好；
本模块只做格式转换与一致性校验，绝不推断任何一场该买什么。
"""
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.decision.legs_audit import (
    CRASH_MARKER_LEXICON,
    DIRECTIONAL_LEXICON,
    TEAM_TAG_LEXICON,
    TRACKING_TAG_LEXICON,
)

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
NONDIRECTIONAL_LEXICON = frozenset({
    "undecided_second_leg", "source_disagreement", "venue_anomaly",
    "two_way_instability", "dressing_room_turmoil",
})


class JudgmentError(ValueError):
    """judgment-v1 结构错误。**宁可抛错也不补默认值**——静默默认会让判读与票面脱节。"""


@dataclass(frozen=True)
class BuildResult:
    reads: list[dict]
    legs: dict
    warnings: list[str]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise JudgmentError(msg)


def build(judgment: dict, *, issue: str, store_ids: dict, fair: dict,
          made_at: str, judge: str = "claude") -> BuildResult:
    """judgment-v1 → (reads, legs)。

    `judgment` = {场次: {action, confidence, directional_flags, nondirectional_flags,
                        anchor_integrity, license_questions, precedents, crash_markers,
                        tracking_tags, team_tags, ttg_shape_anchor, note, belief?}}
    `store_ids` = `<issue>-store-ids.json`（match_id/snapshot_id/name）
    `fair`      = {场次: {home,draw,away}}
    """
    warnings: list[str] = []
    reads: list[dict] = []
    legs: dict[str, dict] = {}
    prescription: dict[str, str] = {}

    for no in sorted(judgment, key=int):
        j = judgment[no]
        _require(no in fair, f"场{no} 缺 fair（禁嘴算：概率只能来自 store 或 devig）")
        _require(no in store_ids, f"场{no} 缺 store_ids（match_id/snapshot_id）")
        sid = store_ids[no]
        action = str(j.get("action") or "").strip()
        _require(bool(action), f"场{no} 缺 action（面集合或 drop）")
        faces = "" if action in ("drop", "丢", "-") else action
        _require(set(faces) <= set(FACE_KEYS),
                 f"场{no} action `{action}` 不是合法面集合")

        prior = fair[no]
        belief = j.get("belief") or prior
        if belief is not prior and belief != prior:
            warnings.append(f"场{no} belief≠prior（净偏移须在 judgment 里带证据等级）")

        dflags = [(f, "1") if isinstance(f, str) else tuple(f)
                  for f in j.get("directional_flags", [])]
        for f, _face in dflags:
            if f not in DIRECTIONAL_LEXICON:
                warnings.append(f"场{no} 方向性旗 `{f}` 不在封闭词典（C0 将报 WARN）")
        for f in j.get("nondirectional_flags", []):
            if f not in NONDIRECTIONAL_LEXICON:
                warnings.append(f"场{no} 无方向旗 `{f}` 不在词典")
        for t in j.get("tracking_tags", []):
            if t not in TRACKING_TAG_LEXICON:
                warnings.append(f"场{no} tracking_tag `{t}` 不在词典")
        for side in ("home", "away"):
            for t in (j.get("team_tags") or {}).get(side, []):
                if t not in TEAM_TAG_LEXICON:
                    warnings.append(f"场{no} team_tag `{t}` 不在词典")
        for m in j.get("crash_markers", []):
            if m not in CRASH_MARKER_LEXICON:
                warnings.append(f"场{no} crash_marker `{m}` 不在词典")

        conf = int(j.get("confidence", 0))
        _require(1 <= conf <= 5, f"场{no} confidence 必须是 1-5，实得 {conf}")

        flag_txt = "/".join(f for f, _ in dflags) or "无"
        nd_txt = "/".join(j.get("nondirectional_flags", [])) or "无"
        note = (f"[{issue}场{no}|{sid.get('name', '')}|四问:{j.get('license_score', 'n/a')}"
                f"|旗:{flag_txt}/{nd_txt}|完整度:{j.get('anchor_integrity', 'unknown')}"
                f"|三证:{j.get('proofs', '')}] {j.get('note', '')}")

        reads.append({
            "read_id": f"R-{judge}-zucai-{issue}-{int(no):02d}-had",
            "match_id": sid["match_id"], "snapshot_id": sid["snapshot_id"],
            "made_at": made_at, "judge": judge, "market": "had",
            "prior": prior, "belief": belief,
            "factors": j.get("factors", []),
            "falsifier": j.get("falsifier")
            or (f"场{no}:被排面/尾面开出→旗与四问评分记入 scoreboard;"
                f"正路兑现→保守成本入账。14:00 备料复核后冻结;18:30 只加面"),
            "confidence": conf, "shadow": False, "note": note,
        })

        prescription[no] = j.get("prescription") or ("310" if faces else "310")
        if not faces:
            continue
        legs[no] = {
            "name": f"{sid.get('name', '')}·{faces}",
            "faces": faces, "confidence": conf,
            "prior": prior, "fair": belief,
            "adjustment_evidence_tiers": j.get("adjustment_evidence_tiers", []),
            "directional_flags": [list(x) for x in dflags],
            "nondirectional_flags": list(j.get("nondirectional_flags", [])),
            "anchor_integrity": j.get("anchor_integrity", "unknown"),
            "precedents": [list(p) for p in j.get("precedents", [])],
            "crash_markers": list(j.get("crash_markers", [])),
            "tracking_tags": list(j.get("tracking_tags", [])),
            "team_tags": j.get("team_tags") or {"home": [], "away": []},
            "license_questions": j.get("license_questions"),
            "ttg_shape_anchor": j.get("ttg_shape_anchor"),
        }

    legs_payload = {
        "issue": issue,
        "version": "base_处方P14（read_builder 生成）",
        "prescription": prescription,
        "deviation_registry": [],
        "legs": legs,
    }
    return BuildResult(reads=reads, legs=legs_payload, warnings=warnings)


def format_warnings(result: BuildResult) -> str:
    head = (f"judgment→reads/legs：{len(result.reads)} 条 Read / "
            f"{len(result.legs['legs'])} 条 legs")
    if not result.warnings:
        return head + "；词典校验全过。"
    return "\n".join([head + f"；{len(result.warnings)} 条词典/偏移提示：",
                      *(f"  ⚠️ {w}" for w in result.warnings)])
