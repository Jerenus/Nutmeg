"""研究 JSON → 判断层的入库桥 —— 把「转录 + 手工清洗」从每期的人工活里拿掉。

**Why.** `read_builder` 吃的是我手敲的 `judgment-v1`；而深研 agent 产出的
`<issue>-research-m<N>.json` 走的是另一条路——每期我在 `/tmp` 写一个 merge 脚本
把它搬进 legs-base，**零校验**。四期下来踩到的坑：

- agent 把叙述写进 `crash_markers`/`nondirectional_flags`（list-in-list），
  污染封闭词典，我每期手工挑出来塞进 note；
- 死亡三证的键名两套并存（`a_no_scoring_mechanism…` vs 裸 `a/b/c`），
  下游读不到就静默当 None；
- 三证 (c) 的**定义**在 agent 之间漂移：宪法口径是「正路完整度 PASS」（一条腿一个值），
  有的 agent 写成「价格证 fair<15%」（一个面一个值）→ 26128 场2 出现
  home/draw 为 true 而 away 为 false 的自相矛盾；
- 编码与正文相反：26128 场7 `q3b=false` 而同一份 summary 写「③b 的答案是『在』」；
- `information_asymmetry` 不在 `NONDIRECTIONAL_LEXICON` 里，agent 照写，
  下游只报一条淹没在 20 条 WARN 里的提示。

**本模块只做转录与一致性校验，绝不产生判断**（同 `read_builder`）：
它不改任何一场的面、不推断动作、不替 agent 改结论。它只回答两个问题——
「这份研究能不能被机器读」和「它有没有自相矛盾」。

⛔**词典外的旗一律不阻断出票**，只被剥离进 note：agent 现场自命名一个旗如果能堵死
单选，那不是纪律是瘫痪（26103 一次冒出三个自造旗）。但**剥离必须留痕**，
否则等于静默丢证据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from nutmeg.decision.legs_audit import (
    CRASH_MARKER_LEXICON,
    DIRECTIONAL_LEXICON,
    PRECEDENT_STATUSES,
    TEAM_TAG_LEXICON,
    TRACKING_TAG_LEXICON,
)
from nutmeg.decision.read_builder import NONDIRECTIONAL_LEXICON

FACE_KEYS = ("home", "draw", "away")
LICENSE_KEYS = (
    "q1_spine",
    "q2_route",
    "q3a_opponent_scores",
    "q3b_opponent_takes_points",
    "q4_no_context_flag",
)
PROOF_KEYS = ("a", "b", "c")
HOLE_LOCATION_UNITS = frozenset(
    {"attack", "creation", "spine", "defense", "goalkeeper", "both", "none"}
)
HOLE_LOCATION_SIDES = frozenset({"home", "away", "both", "none"})
MAX_TAG_LEN = 48
"""词典项都是短 snake_case 名；超过这个长度的几乎一定是叙述被写进了标签位。"""

_PROSE_MARKERS = {
    "q3a_opponent_scores": ("③a", "3a", "q3a"),
    "q3b_opponent_takes_points": ("③b", "3b", "q3b"),
    "q1_spine": ("①脊柱", "q1"),
    "q2_route": ("②正路", "q2"),
}
_AFFIRM = ("成立", "为真", "＝true", "=true", "答案是『在』", "答案是「在」", "判是", "true")
_DENY = ("不成立", "为假", "＝false", "=false", "判否", "判不成立", "false")


@dataclass
class IntakeIssue:
    level: str          # ERROR | WARN
    match_no: int
    field: str
    message: str

    def __str__(self) -> str:
        icon = "❌" if self.level == "ERROR" else "⚠️"
        return f"{icon} 场{self.match_no} [{self.field}] {self.message}"


@dataclass
class IntakeResult:
    match_no: int
    leg: dict
    issues: list[IntakeIssue] = field(default_factory=list)
    stripped: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(issue.level == "ERROR" for issue in self.issues)


def normalize_proofs(raw: object) -> dict[str, dict[str, object]]:
    """死亡三证键名归一：`a_no_scoring_mechanism` / 裸 `a` 都规约成 `a`。

    两套键名并存是 agent 各写各的结果；下游按裸键读就把带后缀的那套静默读成 None，
    于是「三证 0/3」与「三证没填」长得一模一样。
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for face, proofs in raw.items():
        if face not in FACE_KEYS or not isinstance(proofs, dict):
            continue
        normalized: dict[str, object] = {}
        for key, value in proofs.items():
            if key == "detail":
                normalized["detail"] = value
                continue
            head = str(key)[:1].lower()
            if head in PROOF_KEYS and head not in normalized:
                normalized[head] = value
        out[face] = normalized
    return out


def proof_count(proofs: dict[str, object]) -> int:
    return sum(1 for key in PROOF_KEYS if proofs.get(key) is True)


def _check_hole_location(
    raw: object,
    *,
    match_no: int,
    issues: list[IntakeIssue],
) -> None:
    hole = raw if isinstance(raw, dict) else {}
    for key, allowed in (
        ("unit", HOLE_LOCATION_UNITS),
        ("side", HOLE_LOCATION_SIDES),
    ):
        value = hole.get(key)
        if value not in allowed:
            issues.append(
                IntakeIssue(
                    "WARN",
                    match_no,
                    "hole_location_uncontrolled",
                    f"hole_location.{key} `{value}` 不在闭合值域 {sorted(allowed)}",
                )
            )


def _sanitize_tags(
    values: object,
    lexicon: frozenset[str],
    *,
    match_no: int,
    label: str,
    issues: list[IntakeIssue],
    stripped: list[str],
) -> list[str]:
    """留在词典里的原样保留；词典外的**剥离进 note 并留痕**，绝不静默丢。"""
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        issues.append(IntakeIssue("ERROR", match_no, label, "必须是数组"))
        return []
    kept: list[str] = []
    for item in values:
        if isinstance(item, list | dict):
            issues.append(
                IntakeIssue(
                    "ERROR", match_no, label,
                    f"标签位写进了嵌套结构 {str(item)[:40]}… —— "
                    "封闭词典只收短名，叙述请写 note",
                )
            )
            stripped.append(f"{label}: {str(item)[:120]}")
            continue
        text = str(item).strip()
        if len(text) > MAX_TAG_LEN:
            issues.append(
                IntakeIssue(
                    "ERROR", match_no, label,
                    f"标签位写进了叙述（{len(text)} 字）：{text[:40]}…",
                )
            )
            stripped.append(f"{label}: {text[:200]}")
            continue
        if text in lexicon:
            kept.append(text)
        else:
            issues.append(
                IntakeIssue(
                    "WARN", match_no, label,
                    f"`{text}` 不在封闭词典 → 已剥离进 note（不阻断出票）",
                )
            )
            stripped.append(f"{label}: {text}")
    return kept


def _sanitize_directional(
    values: object,
    *,
    match_no: int,
    issues: list[IntakeIssue],
    stripped: list[str],
) -> list[list[str]]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        issues.append(IntakeIssue("ERROR", match_no, "directional_flags", "必须是数组"))
        return []
    kept: list[list[str]] = []
    for item in values:
        pair = item if isinstance(item, list | tuple) else (item, "1")
        if len(pair) != 2:
            issues.append(
                IntakeIssue(
                    "ERROR", match_no, "directional_flags",
                    f"方向性旗必须是 [旗名, 面] 二元组，实得 {str(item)[:40]}",
                )
            )
            continue
        name, face = str(pair[0]).strip(), str(pair[1]).strip()
        if name not in DIRECTIONAL_LEXICON:
            issues.append(
                IntakeIssue(
                    "WARN", match_no, "directional_flags",
                    f"`{name}` 不在封闭词典 → 已剥离进 note（C0 会再报一次）",
                )
            )
            stripped.append(f"directional_flags: {name}→{face}")
            continue
        if face not in ("3", "1", "0"):
            issues.append(
                IntakeIssue(
                    "ERROR", match_no, "directional_flags",
                    f"`{name}` 指向的面 `{face}` 不是 3/1/0",
                )
            )
            continue
        kept.append([name, face])
    return kept


def _check_license(
    license_questions: dict,
    dflags: list,
    ndflags: list,
    prose: str,
    *,
    match_no: int,
    issues: list[IntakeIssue],
) -> None:
    has_flag = bool(dflags) or bool(ndflags)
    q4 = license_questions.get("q4_no_context_flag")
    if q4 is True and has_flag:
        issues.append(
            IntakeIssue(
                "ERROR", match_no, "license_questions",
                "④『无情境旗』判 true，但本场挂着旗 —— 四问④与旗行直接矛盾",
            )
        )
    if q4 is False and not has_flag:
        issues.append(
            IntakeIssue(
                "WARN", match_no, "license_questions",
                "④判 false 却零旗；若依据是 C9 机理请写进 note，否则四问会被低估",
            )
        )
    for key, markers in _PROSE_MARKERS.items():
        coded = license_questions.get(key)
        if coded is None:
            continue
        for marker in markers:
            for hit in re.finditer(re.escape(marker), prose):
                window = prose[hit.end(): hit.end() + 24]
                affirmed = any(word in window for word in _AFFIRM)
                denied = any(word in window for word in _DENY)
                if affirmed and not denied and coded is False:
                    issues.append(
                        IntakeIssue(
                            "WARN", match_no, "license_questions",
                            f"{key} 编码 false，正文却写「{marker}{window.strip()[:16]}」"
                            " —— 编码与正文可能相反，人工复核",
                        )
                    )
                    return
                if denied and not affirmed and coded is True:
                    issues.append(
                        IntakeIssue(
                            "WARN", match_no, "license_questions",
                            f"{key} 编码 true，正文却写「{marker}{window.strip()[:16]}」"
                            " —— 编码与正文可能相反，人工复核",
                        )
                    )
                    return


def _check_proofs(
    proofs: dict[str, dict[str, object]],
    anchor_integrity: str,
    dead_face: str | None,
    *,
    match_no: int,
    issues: list[IntakeIssue],
) -> None:
    c_values = {face: p.get("c") for face, p in proofs.items() if "c" in p}
    distinct = {value for value in c_values.values() if value is not None}
    if len(distinct) > 1:
        issues.append(
            IntakeIssue(
                "WARN", match_no, "death_three_proofs",
                f"三证(c) 在各面之间不一致 {c_values} —— (c) 的宪法口径是"
                "「正路完整度 PASS」，一条腿只有一个值；逐面不同说明用的是别的定义",
            )
        )
    canonical = anchor_integrity == "pass"
    for face, value in c_values.items():
        if value is not None and value is not canonical:
            issues.append(
                IntakeIssue(
                    "WARN", match_no, "death_three_proofs",
                    f"{face} 的 (c)={value} 与完整度 `{anchor_integrity}` 不符"
                    f"（应为 {canonical}）—— (c) 定义漂移，按完整度重读",
                )
            )
            break
    if dead_face and dead_face not in ("none", "—", ""):
        face = {"3": "home", "1": "draw", "0": "away"}.get(dead_face, dead_face)
        count = proof_count(proofs.get(face, {}))
        if count < 3:
            issues.append(
                IntakeIssue(
                    "ERROR", match_no, "structurally_dead_face",
                    f"宣告 `{dead_face}` 结构性死亡，但三证只成立 {count}/3 —— "
                    "死面必须三证齐；不齐只能叫「被削弱」",
                )
            )


_NO_PRECEDENT_PROSE = (
    "无——", "无先例", "不存在", "查无", "没有先例", "无任何",
    "未查到", "未找到", "无可用", "无同型", "零先例", "无法核实",
)
"""「查无先例」的措辞表。真正的 dead 先例描述的是一场**发生过的**比赛
（"2021 欧联,格拉茨风暴 1-1 平摩纳哥"），不会命中这些词。"""


def _check_precedents(
    raw: object,
    *,
    match_no: int,
    issues: list[IntakeIssue],
) -> list[list]:
    """先例三元组 (面, 描述, 状态)。**「查无先例」必须记 `none`，不是 `dead`。**

    出生事故 2026-09-17：agent 把"这个面根本没有同型先例"记成 `dead`
    （26128 场14：`["1","无——马拉卡纳同型对独立谷不存在 90' 平局先例","dead"]`），
    而 C14 的豁免看的正是 `dead` —— 于是**证据的缺席被当成了积极证据**。
    嗅探散文这件事只能发生在这座桥上，绝不能进审计门（门不听论证、也不读散文）。
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        issues.append(IntakeIssue("ERROR", match_no, "precedents", "必须是数组"))
        return []
    out: list[list] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) != 3:
            issues.append(IntakeIssue(
                "ERROR", match_no, "precedents",
                f"先例必须是 [面, 描述, 状态] 三元组，实得 {str(item)[:40]}",
            ))
            continue
        face, desc, status = (str(x) for x in item)
        if status not in PRECEDENT_STATUSES:
            issues.append(IntakeIssue(
                "ERROR", match_no, "precedents",
                f"状态 `{status}` 不在词典（alive/dead/none）",
            ))
            continue
        if status == "dead" and any(k in desc for k in _NO_PRECEDENT_PROSE):
            issues.append(IntakeIssue(
                "ERROR", match_no, "precedents",
                f"「{desc[:28]}…」读起来是**查无先例**却记成 `dead`。"
                "死亡三证(b) 要的是「载体已不在阵」这个积极证据；"
                "「没查到」是证据的缺席，请记 `none`——"
                "记错会让 C14 的昂贵排除豁免凭空成立（26127 场3/场7）",
            ))
            continue
        out.append([face, desc, status])
    return out


def intake(research: dict, leg: dict) -> IntakeResult:
    """一场研究 JSON → 可入库的 leg 字段 + 问题清单。**不改 faces、不产生判断。**"""
    match_no = int(research.get("match_no") or leg.get("match_no") or 0)
    issues: list[IntakeIssue] = []
    stripped: list[str] = []

    anchor_integrity = str(
        research.get("anchor_integrity")
        or research.get("favourite_integrity")
        or "unknown"
    )
    if anchor_integrity not in ("pass", "fail", "symmetric_damage", "unknown"):
        issues.append(
            IntakeIssue(
                "ERROR", match_no, "anchor_integrity",
                f"`{anchor_integrity}` 不是 pass/fail/symmetric_damage/unknown",
            )
        )
        anchor_integrity = "unknown"

    confidence = research.get("confidence")
    try:
        confidence = int(confidence)
    except (TypeError, ValueError):
        issues.append(
            IntakeIssue("ERROR", match_no, "confidence", "缺 confidence（1-5）")
        )
        confidence = 3
    if not 1 <= confidence <= 5:
        issues.append(
            IntakeIssue(
                "ERROR", match_no, "confidence", f"confidence {confidence} 不在 1-5"
            )
        )
        confidence = 3

    dflags = _sanitize_directional(
        research.get("directional_flags"),
        match_no=match_no, issues=issues, stripped=stripped,
    )
    ndflags = _sanitize_tags(
        research.get("nondirectional_flags"), NONDIRECTIONAL_LEXICON,
        match_no=match_no, label="nondirectional_flags",
        issues=issues, stripped=stripped,
    )
    crash = _sanitize_tags(
        research.get("crash_markers"), CRASH_MARKER_LEXICON,
        match_no=match_no, label="crash_markers", issues=issues, stripped=stripped,
    )
    tracking = _sanitize_tags(
        research.get("tracking_tags"), TRACKING_TAG_LEXICON,
        match_no=match_no, label="tracking_tags", issues=issues, stripped=stripped,
    )
    team_tags = {}
    for side in ("home", "away"):
        team_tags[side] = _sanitize_tags(
            (research.get("team_tags") or {}).get(side), TEAM_TAG_LEXICON,
            match_no=match_no, label=f"team_tags.{side}",
            issues=issues, stripped=stripped,
        )

    license_questions = research.get("license_questions") or {}
    if not isinstance(license_questions, dict):
        issues.append(
            IntakeIssue("ERROR", match_no, "license_questions", "必须是对象")
        )
        license_questions = {}
    prose = " ".join(
        str(research.get(key, "") or "")
        for key in ("summary", "note", "weakest_face_note")
    ) + " " + str(license_questions.get("notes", "") or "")
    _check_license(
        license_questions, dflags, ndflags, prose,
        match_no=match_no, issues=issues,
    )

    proofs = normalize_proofs(research.get("death_three_proofs"))
    _check_proofs(
        proofs, anchor_integrity, research.get("structurally_dead_face"),
        match_no=match_no, issues=issues,
    )
    _check_hole_location(
        research.get("hole_location"), match_no=match_no, issues=issues
    )

    note = str(research.get("summary", "") or "")[:400]
    if stripped:
        note = (note + "｜【入库剥离】" + "；".join(stripped))[:900]

    merged = {
        **leg,
        "anchor_integrity": anchor_integrity,
        "confidence": confidence,
        "directional_flags": dflags,
        "nondirectional_flags": ndflags,
        "crash_markers": crash,
        "tracking_tags": tracking,
        "team_tags": team_tags,
        "precedents": _check_precedents(
            research.get("precedents"), match_no=match_no, issues=issues
        ),
        "license_questions": {key: license_questions.get(key) for key in LICENSE_KEYS},
        "note": note,
        "_nominal": research.get("nominal_favourite") or research.get("anchor_side"),
        "_dead_face": research.get("structurally_dead_face"),
        "_hole": research.get("hole_location"),
        "_d3": proofs,
    }
    return IntakeResult(match_no=match_no, leg=merged, issues=issues, stripped=stripped)


def format_report(results: list[IntakeResult]) -> str:
    """人读回执。**问题清单不折叠**——静默降级正是这条桥要消灭的东西。"""
    errors = sum(1 for r in results for i in r.issues if i.level == "ERROR")
    warns = sum(1 for r in results for i in r.issues if i.level == "WARN")
    lines = [
        f"研究入库：{len(results)} 场 ｜ {errors} ERROR ／ {warns} WARN"
        + ("  ⛔有 ERROR 的场次未写入" if errors else ""),
        "",
    ]
    for result in sorted(results, key=lambda r: r.match_no):
        leg = result.leg
        flags = "/".join(f"{n}→{f}" for n, f in leg["directional_flags"]) or "—"
        q3b = leg["license_questions"].get("q3b_opponent_takes_points")
        lines.append(
            f"  场{result.match_no:<3}{str(leg.get('name', ''))[:14]:16}"
            f"完整度={leg['anchor_integrity']:16}旗={flags:26}"
            f"③b={q3b}  conf={leg['confidence']}"
            + ("  ⛔未写入" if result.blocked else "")
        )
        for issue in result.issues:
            lines.append(f"      {issue}")
    return "\n".join(lines)
