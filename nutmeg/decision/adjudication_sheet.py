"""裁决单 —— 把「行权」从一行 reason 升格成可结账的判断。

**出生事故。** 2026-09-14~17 热板四连（26125/26126/26127/26128，Σtop1 8.52/8.39/7.81/8.32）
严格裁决全部空仓，而同期行权形状 26125 纸面 8/9、26126 实票 8/9、26127 试玩 9/9。
门的判断（禁裸）是对的——26127 唯一断腿的两张恰是降双硬币场；但「洞已定价≠翻车」
这条本体结论**没有出口**：每个 ERROR 要手写 `deviation_registry`，rx 预测另立文件，
`strict_ruling_vs_override` 只能复盘时手补。结果是守门与行权两条路**都没有可累积的账**，
四期过去我仍然只能靠散文说"这次该不该行权"。

**本模块只做文书，不做判断**（同 B4c 面集展开）：

- `issue_sheet` 把当前 ERROR 集摊成一张**留空**的裁决单——机器绝不预填 `ruling`；
- `validate_sheet` 检查人填完整：每条 ERROR 都有裁决；每条**驳回**附条名 + 理由 +
  **至少一条可证伪预测**；
- `apply_sheet` 把驳回落回 legs 的 `deviation_registry`（供既有 `--user-override`
  通道入账 Adjudication），预测落 rx 文件。

⛔**驳回必须带可证伪预测**，是本模块加的唯一新门槛，且只加在驳回一侧。
理由：26098/26101/26102/26103 四次撤保险，每次理由都比上次更讲究、也都亏，
说明**理由的质量不可自证**；能自证的只有事后可判真假的断言。
没有 falsifier 的驳回 = 不可结账的驳回。

⛔本模块**不放宽任何门**。`has_blocking` 仍然为真，退出码仍然是 1，
`--user-override` 仍然只有 Jun 能按、仍然要 Web 工位签发的 token。
它只把"按下去之前必须写清楚什么"变成机器可校验的。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nutmeg.decision.legs_audit import (
    Finding,
    canonical_rule_id,
    short_code,
)

RULING_ACCEPT = "accept"
RULING_REJECT = "reject"
_RULINGS = (RULING_ACCEPT, RULING_REJECT)

_RULING_LABEL = {
    RULING_ACCEPT: "接受门（改票，不出这张）",
    RULING_REJECT: "驳回门（知情行权，入 evidence_rejected）",
}

TICKET_SCOPE = "ticket"
"""票级 ERROR 的 slot 标记。C15/C15b/C17 没有单一 match_no 可挂。"""


class AdjudicationSheetError(RuntimeError):
    """裁决单不完整、与票面漂移、或试图用它绕过门。"""


@dataclass(frozen=True)
class RulingSlot:
    """一条 ERROR 的裁决位。`ruling` 留空 = judgment 尚未落下。"""

    audit_code: str
    code: str
    match_no: int | None
    match_name: str
    finding: str
    since: str
    ruling: str
    rule_ids: tuple[str, ...]
    reason: str
    predictions: tuple[dict[str, str], ...]

    @property
    def scope(self) -> str:
        return TICKET_SCOPE if self.match_no is None else "match"

    @property
    def signature(self) -> str:
        return f"{self.audit_code}@{'-' if self.match_no is None else self.match_no}"


def error_signature(findings: list[Finding]) -> str:
    """当前 ERROR 集的指纹。裁决单签发后票面被改过 → 指纹不符 → 拒绝行权。"""
    marks = sorted(
        f"{short_code(finding.code)}@"
        f"{'-' if finding.match_no is None else finding.match_no}"
        for finding in findings
        if finding.level == "ERROR"
    )
    return "|".join(marks)


def _leg_name(payload: dict, match_no: int | None) -> str:
    if match_no is None:
        return "（票级）"
    leg = (payload.get("legs") or {}).get(str(match_no)) or {}
    return str(leg.get("name", "") or "")


def issue_sheet(
    payload: dict,
    findings: list[Finding],
    *,
    legs_file: Path,
    issued_at: datetime,
) -> dict:
    """签发一张留空的裁决单。**机器不填 `ruling`，这是判断不是算术。**"""
    errors = [finding for finding in findings if finding.level == "ERROR"]
    if not errors:
        raise AdjudicationSheetError("本票没有 ERROR，无需裁决单")
    rulings = [
        {
            "audit_code": short_code(finding.code),
            "code": finding.code,
            "match_no": finding.match_no,
            "match_name": _leg_name(payload, finding.match_no),
            "scope": TICKET_SCOPE if finding.match_no is None else "match",
            "finding": finding.message,
            "since": finding.since,
            # —— 以下四项留空给判断 ——
            "ruling": "",
            "rule_ids": [],
            "reason": "",
            "predictions": [],
        }
        for finding in sorted(
            errors,
            key=lambda item: (
                item.match_no is None,
                item.match_no or 0,
                short_code(item.code),
            ),
        )
    ]
    return {
        "issue": str(payload.get("issue", "")),
        "legs_version": str(payload.get("version", "") or legs_file.stem),
        "legs_file": str(legs_file),
        "issued_at": issued_at.isoformat(timespec="seconds"),
        "error_signature": error_signature(findings),
        "how_to": [
            "每条 ERROR 填一个 ruling：accept=接受门（改票，这张不出）／"
            "reject=驳回门（知情行权）。",
            "机器不会替你填 ruling —— 判断永不入脚本。",
            "reject 必须同时给出：rule_ids（RULEBOOK 已登记条名）、reason（一行）、"
            "predictions（≥1 条，每条含 claim 与 falsifier）。",
            "没有 falsifier 的驳回是不可结账的驳回：26098-26103 四次撤保险"
            "理由一次比一次讲究且全亏，理由的质量不可自证。",
            "填完跑 `nutmeg decision-adjudicate --apply <本文件>`；"
            "它只落文书，真正的门仍是 `decision-audit-legs --user-override`。",
        ],
        "rulings": rulings,
    }


def _parse_predictions(raw: object, *, where: str) -> tuple[dict[str, str], ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list):
        raise AdjudicationSheetError(f"{where} predictions 必须是数组")
    parsed: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise AdjudicationSheetError(f"{where} 第 {index} 条预测必须是对象")
        claim = str(item.get("claim", "") or "").strip()
        falsifier = str(item.get("falsifier", "") or "").strip()
        if not claim or not falsifier:
            raise AdjudicationSheetError(
                f"{where} 第 {index} 条预测缺 claim 或 falsifier —— "
                "不可证伪的断言不进账"
            )
        entry = {"claim": claim, "falsifier": falsifier}
        if item.get("id"):
            entry["id"] = str(item["id"]).strip()
        parsed.append(entry)
    return tuple(parsed)


def parse_sheet(sheet: dict) -> tuple[RulingSlot, ...]:
    """把填好的裁决单读成 slot；只做形状校验，完整性交给 `validate_sheet`。"""
    raw = sheet.get("rulings")
    if not isinstance(raw, list) or not raw:
        raise AdjudicationSheetError("裁决单缺 rulings 数组")
    slots: list[RulingSlot] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise AdjudicationSheetError(f"第 {index} 条裁决位必须是对象")
        match_no = item.get("match_no")
        where = (
            "票级 ERROR"
            if match_no is None
            else f"场{match_no}"
        ) + f" {item.get('audit_code', '')}"
        rule_ids = item.get("rule_ids") or []
        if not isinstance(rule_ids, list):
            raise AdjudicationSheetError(f"{where} rule_ids 必须是数组")
        slots.append(
            RulingSlot(
                audit_code=str(item.get("audit_code", "") or ""),
                code=str(item.get("code", "") or ""),
                match_no=None if match_no is None else int(match_no),
                match_name=str(item.get("match_name", "") or ""),
                finding=str(item.get("finding", "") or ""),
                since=str(item.get("since", "") or ""),
                ruling=str(item.get("ruling", "") or "").strip().lower(),
                rule_ids=tuple(str(rule_id) for rule_id in rule_ids),
                reason=str(item.get("reason", "") or "").strip(),
                predictions=_parse_predictions(item.get("predictions"), where=where),
            )
        )
    return tuple(slots)


def validate_sheet(
    sheet: dict,
    findings: list[Finding],
) -> tuple[RulingSlot, ...]:
    """校验裁决单：指纹对得上、每条都裁了、每条驳回都可结账。"""
    signature = error_signature(findings)
    recorded = str(sheet.get("error_signature", "") or "")
    if recorded != signature:
        raise AdjudicationSheetError(
            "裁决单与当前票面的 ERROR 集不符 —— 签发后票面被改过。\n"
            f"  单上：{recorded or '（空）'}\n"
            f"  现在：{signature or '（空）'}\n"
            "重新签发裁决单，不要在旧单上行权。"
        )
    slots = parse_sheet(sheet)
    blank = [slot for slot in slots if not slot.ruling]
    if blank:
        marks = "、".join(slot.signature for slot in blank)
        raise AdjudicationSheetError(f"以下 ERROR 还没裁：{marks}")
    bad = [slot for slot in slots if slot.ruling not in _RULINGS]
    if bad:
        marks = "、".join(f"{slot.signature}={slot.ruling}" for slot in bad)
        raise AdjudicationSheetError(
            f"ruling 只能是 accept 或 reject：{marks}"
        )
    for slot in slots:
        if slot.ruling != RULING_REJECT:
            continue
        if not slot.reason:
            raise AdjudicationSheetError(f"{slot.signature} 驳回缺 reason")
        known = [
            rule_id
            for rule_id in slot.rule_ids
            if canonical_rule_id(rule_id) is not None
        ]
        if not known:
            raise AdjudicationSheetError(
                f"{slot.signature} 驳回缺**已登记**条名（rule_ids）；"
                f"填的是 {list(slot.rule_ids) or '（空）'}，"
                "无名偏离不构成行权理由"
            )
        if not slot.predictions:
            raise AdjudicationSheetError(
                f"{slot.signature} 驳回缺可证伪预测 —— "
                "理由的质量不可自证，只有 falsifier 能结账"
            )
    return slots


def accepted_slots(slots: tuple[RulingSlot, ...]) -> tuple[RulingSlot, ...]:
    return tuple(slot for slot in slots if slot.ruling == RULING_ACCEPT)


def rejected_slots(slots: tuple[RulingSlot, ...]) -> tuple[RulingSlot, ...]:
    return tuple(slot for slot in slots if slot.ruling == RULING_REJECT)


def merge_deviation_registry(payload: dict, slots: tuple[RulingSlot, ...]) -> dict:
    """把驳回写回 `deviation_registry`；同场同条名的旧登记被本次裁决替换。

    票级 ERROR 写 `scope="ticket"` 条目 —— 它没有 match_no，
    26128 的 C17 是第一个真实样本。
    """
    existing = payload.get("deviation_registry") or []
    if not isinstance(existing, list):
        raise AdjudicationSheetError("deviation_registry must be a list")
    rejected = rejected_slots(slots)
    superseded = {
        (slot.match_no, slot.code) for slot in rejected
    }
    kept = [
        item
        for item in existing
        if not (
            isinstance(item, dict)
            and (
                (
                    None if item.get("match_no") is None else int(item["match_no"]),
                    str(item.get("audit_code", "") or ""),
                )
                in superseded
            )
        )
    ]
    added = []
    for slot in rejected:
        entry: dict[str, object] = {
            "rule_ids": [
                rule_id
                for rule_id in slot.rule_ids
                if canonical_rule_id(rule_id) is not None
            ],
            "reason": slot.reason,
            "user_override": True,
            "audit_code": slot.code,
        }
        if slot.match_no is None:
            entry["scope"] = TICKET_SCOPE
        else:
            entry["match_no"] = slot.match_no
        added.append(entry)
    return {**payload, "deviation_registry": [*kept, *added]}


def prediction_records(
    slots: tuple[RulingSlot, ...],
    *,
    start_index: int = 1,
) -> list[dict[str, str]]:
    """把驳回附带的预测编号成 rx 条目。编号只在写入时分配，裁决单里可以不填。"""
    records: list[dict[str, str]] = []
    index = start_index
    for slot in rejected_slots(slots):
        for prediction in slot.predictions:
            records.append(
                {
                    "id": prediction.get("id") or f"P{index}",
                    "claim": prediction["claim"],
                    "falsifier": prediction["falsifier"],
                    "origin": f"裁决驳回 {slot.signature} {slot.code}",
                }
            )
            index += 1
    return records


def merge_rx_predictions(
    rx_path: Path,
    records: list[dict[str, str]],
    *,
    issue: str,
    registered_at: datetime,
) -> dict:
    """把预测并入 rx 文件；同 claim 的旧条目不重复追加。"""
    if rx_path.exists():
        document = json.loads(rx_path.read_text("utf-8"))
        if not isinstance(document, dict):
            raise AdjudicationSheetError(f"{rx_path} 不是 rx 对象")
    else:
        document = {
            "issue": issue,
            "registered_at": registered_at.isoformat(timespec="minutes"),
            "predictions": [],
        }
    predictions = document.get("predictions")
    if not isinstance(predictions, list):
        raise AdjudicationSheetError(f"{rx_path} 的 predictions 不是数组")
    seen = {
        str(item.get("claim", ""))
        for item in predictions
        if isinstance(item, dict)
    }
    used = {
        str(item.get("id", ""))
        for item in predictions
        if isinstance(item, dict)
    }
    appended = []
    next_index = len(predictions) + 1
    for record in records:
        if record["claim"] in seen:
            continue
        entry = dict(record)
        while entry["id"] in used:
            entry["id"] = f"P{next_index}"
            next_index += 1
        used.add(entry["id"])
        appended.append(entry)
    document["predictions"] = [*predictions, *appended]
    return document


def format_sheet_summary(slots: tuple[RulingSlot, ...]) -> str:
    """行权前的人读回执 —— 让「我到底驳了几条门」无法被略过。"""
    accepted = accepted_slots(slots)
    rejected = rejected_slots(slots)
    lines = [
        f"裁决：{len(slots)} 条 ERROR → 接受 {len(accepted)} / 驳回 {len(rejected)}",
        "",
    ]
    for slot in slots:
        head = (
            f"  {_RULING_LABEL[slot.ruling]}  [{slot.audit_code}] "
            f"{'票级' if slot.match_no is None else f'场{slot.match_no}'}"
            f" {slot.match_name}".rstrip()
        )
        lines.append(head)
        if slot.ruling == RULING_REJECT:
            lines.append(f"      条名 {'／'.join(slot.rule_ids)}｜{slot.reason}")
            for prediction in slot.predictions:
                lines.append(
                    f"      预测 {prediction['claim']}"
                    f"  ⟂ {prediction['falsifier']}"
                )
    return "\n".join(lines)
