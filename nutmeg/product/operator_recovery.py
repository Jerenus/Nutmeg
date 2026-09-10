"""Stable recovery-code mapping for operator-facing surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass

from nutmeg.product.operator_contracts import OperatorBlockViewV1, OperatorRecoveryCode

_TASK_KEY = re.compile(r"^(?P<lane>jczq|zucai):(?P<business_key>[A-Za-z0-9-]+)$")


@dataclass(frozen=True, slots=True)
class OperatorRecoveryDefinition:
    message: str
    repair_owner: str
    action_label: str
    default_recovery_href: str | None = None


def _definition(
    message: str,
    repair_owner: str,
    action_label: str,
    default_recovery_href: str | None = None,
) -> OperatorRecoveryDefinition:
    return OperatorRecoveryDefinition(
        message=message,
        repair_owner=repair_owner,
        action_label=action_label,
        default_recovery_href=default_recovery_href,
    )


OPERATOR_RECOVERY_CATALOG: dict[OperatorRecoveryCode, OperatorRecoveryDefinition] = {
    OperatorRecoveryCode.OFFICIAL_SCHEDULE_MISSING: _definition(
        "今日官方赛程尚未形成可工作的任务。", "外部采集", "恢复官方赛程采集"
    ),
    OperatorRecoveryCode.IDENTITY_UNRESOLVED: _definition(
        "比赛或球队身份尚未完成唯一对齐。", "实体维护", "完成身份对齐"
    ),
    OperatorRecoveryCode.EVIDENCE_MISSING: _definition(
        "赛前证据尚未达到冻结条件。", "外部采集", "补齐缺失证据"
    ),
    OperatorRecoveryCode.EVIDENCE_STALE: _definition(
        "证据已超过当前任务允许的时效。", "外部采集", "刷新过期证据"
    ),
    OperatorRecoveryCode.EVIDENCE_CONFLICT: _definition(
        "必需证据存在尚未清偿的冲突。", "主循环裁决", "清偿证据冲突"
    ),
    OperatorRecoveryCode.SOURCE_CONTRACT_INVALID: _definition(
        "结构化来源未通过版本与字段校验。", "数据运维", "修复来源后重试"
    ),
    OperatorRecoveryCode.TASK_SNAPSHOT_CHANGED: _definition(
        "任务快照已变化，当前页面不能继续提交。",
        "当前操作者",
        "返回今日待办重新打开",
        "/operator-next",
    ),
    OperatorRecoveryCode.AUDIT_ERROR: _definition(
        "候选票审计存在 ERROR，不能继续审批。", "主循环裁决", "返回修改或实名裁决"
    ),
    OperatorRecoveryCode.CONFIRMATION_EXPIRED: _definition(
        "本人确认已超过有效截止时刻。", "截止扫描", "等待未出票回执"
    ),
    OperatorRecoveryCode.TELEGRAM_UPDATE_OWNER_CONFLICT: _definition(
        "Telegram 更新存在多个消费方。",
        "运行维护",
        "核对 Telegram 所有权",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.TELEGRAM_OWNER_MISSING: _definition(
        "Telegram 确认处理器尚未声明所有权。",
        "运行维护",
        "启动唯一确认处理器",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.TELEGRAM_OWNER_HEARTBEAT_EXPIRED: _definition(
        "Telegram 确认处理器心跳已过期。",
        "运行维护",
        "恢复确认处理器",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.TELEGRAM_OWNER_CLOCK_SKEW: _definition(
        "Telegram 确认处理器时钟异常。",
        "运行维护",
        "校准主机时钟",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.TELEGRAM_OWNER_UNAVAILABLE: _definition(
        "Telegram 确认处理器状态不可用。",
        "运行维护",
        "检查确认处理器",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.DIAGNOSTIC_UNAVAILABLE: _definition(
        "本机运行诊断暂不可用。",
        "运行维护",
        "恢复只读诊断",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.PLACEMENT_LEDGER_INTEGRITY: _definition(
        "出票确认与资金账尚未形成一致记录。", "账本核对", "核对 Action 与资金账"
    ),
    OperatorRecoveryCode.RESULT_SOURCE_MISSING: _definition(
        "正式赛果来源尚未齐备。", "外部采集", "补齐正式赛果来源"
    ),
    OperatorRecoveryCode.RESULT_PENDING: _definition(
        "比赛已延期，当前不能形成最终赛果。", "外部采集", "等待补赛或官方作废"
    ),
    OperatorRecoveryCode.RESULT_SOURCE_CONFLICT: _definition(
        "正规化后的 90 分钟赛果来源不一致。", "结果核对", "更正冲突赛果"
    ),
    OperatorRecoveryCode.PROJECTION_STALE: _definition(
        "记分牌投影落后于当前 Action 日志。", "投影维护", "重建记分牌投影"
    ),
    OperatorRecoveryCode.PROJECTION_UNAVAILABLE: _definition(
        "记分牌投影尚不可用。", "投影维护", "建立记分牌投影"
    ),
    OperatorRecoveryCode.SCOREBOARD_AUTHORITY_UNAVAILABLE: _definition(
        "记分牌权威文件当前不可用。",
        "记分牌维护",
        "恢复记分牌权威文件",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.APP_INSTANCE_CONFLICT: _definition(
        "另一个可写应用实例正在占用同一数据目录。",
        "运行维护",
        "关闭重复实例",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.ONTOLOGY_MAINTENANCE_CONFLICT: _definition(
        "本体维护与当前写入事务冲突。",
        "运行维护",
        "等待维护锁释放",
        "/operator-next/maintenance",
    ),
    OperatorRecoveryCode.COMMAND_UNAVAILABLE: _definition(
        "当前应用实例未安装该操作。", "应用维护", "返回今日待办", "/operator-next"
    ),
    OperatorRecoveryCode.OFFICIAL_HISTORY_UNAVAILABLE: _definition(
        "足彩官方奖金历史暂不可用。", "外部采集", "稍后重新采集"
    ),
    OperatorRecoveryCode.PROTECTED_ARTIFACT_BINDING_MISSING: _definition(
        "受保护票据缺少正式决策绑定。", "账本核对", "运行完整性审计"
    ),
    OperatorRecoveryCode.PROTECTED_ARTIFACT_MISSING: _definition(
        "当前任务缺少正式出票制品。", "出票工作台", "返回出票工作台"
    ),
    OperatorRecoveryCode.SELECTED_CANDIDATE_MISSING: _definition(
        "已提交选择对应的候选票不存在。", "出票工作台", "重新选择候选票"
    ),
    OperatorRecoveryCode.OPERATOR_TASK_BLOCKED: _definition(
        "当前工作项需要先完成确定性恢复。", "数据运维", "查看恢复步骤"
    ),
    OperatorRecoveryCode.OPERATOR_INPUTS_MISSING: _definition(
        "本任务缺少严格证据或结构化输入。", "外部采集", "采集并导入任务数据"
    ),
    OperatorRecoveryCode.ODDS_SNAPSHOT_STALE: _definition(
        "赔率快照已超过当前任务允许的时效。", "外部采集", "刷新赔率快照"
    ),
    OperatorRecoveryCode.TICKET_AUDIT_BLOCKED: _definition(
        "票面审计阻止当前票继续推进。", "主循环裁决", "返回调整票面"
    ),
    OperatorRecoveryCode.WAITING_FOR_SOURCE: _definition(
        "下一批确定性来源尚未到达。", "外部采集", "到时重新检查"
    ),
}


def _value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def normalize_recovery_code(
    value: object,
    *,
    fallback: OperatorRecoveryCode = OperatorRecoveryCode.OPERATOR_TASK_BLOCKED,
) -> OperatorRecoveryCode:
    raw = _value(value)
    try:
        return OperatorRecoveryCode(raw)
    except (TypeError, ValueError):
        return fallback


def recovery_code_for_step(step: object) -> OperatorRecoveryCode | None:
    kind = _value(getattr(step, "kind", None))
    if kind in {"blocked", "waiting_data", "prepare"}:
        recovery = getattr(step, "recovery", None)
        code = getattr(recovery, "code", None)
        return normalize_recovery_code(code) if code is not None else None
    if kind == "prepare_evidence":
        gate_state = _value(getattr(step, "gate_state", None))
        if gate_state == "complete":
            return None
        for match in getattr(step, "matches", ()):
            for requirement in getattr(match, "requirements", ()):
                if (
                    _value(getattr(requirement, "requirement_id", None)) == "E1"
                    and _value(getattr(requirement, "state", None)) != "complete"
                ):
                    return OperatorRecoveryCode.IDENTITY_UNRESOLVED
        return {
            "missing": OperatorRecoveryCode.EVIDENCE_MISSING,
            "stale": OperatorRecoveryCode.EVIDENCE_STALE,
            "conflict": OperatorRecoveryCode.EVIDENCE_CONFLICT,
        }.get(gate_state, OperatorRecoveryCode.EVIDENCE_MISSING)
    if kind == "audit_deployment" and getattr(step, "audit_state", None) == "error":
        return OperatorRecoveryCode.AUDIT_ERROR
    if (
        kind == "await_confirmation"
        and getattr(step, "confirmation_state", None) == "expired"
    ):
        return OperatorRecoveryCode.CONFIRMATION_EXPIRED
    if kind == "await_ledger":
        return OperatorRecoveryCode.PLACEMENT_LEDGER_INTEGRITY
    if kind == "await_result":
        blocking_codes = {_value(item) for item in getattr(step, "blocking_codes", ())}
        if (
            getattr(step, "settlement_state", None) == "integrity_blocked"
            or "placement_integrity_blocked" in blocking_codes
        ):
            return OperatorRecoveryCode.PLACEMENT_LEDGER_INTEGRITY
        return {
            "not_imported": OperatorRecoveryCode.RESULT_SOURCE_MISSING,
            "missing": OperatorRecoveryCode.RESULT_SOURCE_MISSING,
            "postponed": OperatorRecoveryCode.RESULT_PENDING,
            "conflict": OperatorRecoveryCode.RESULT_SOURCE_CONFLICT,
        }.get(_value(getattr(step, "result_state", None)))
    return None


def recovery_block_for_step(
    step: object,
    *,
    recovery_link: str,
    reevaluate_at=None,
    fallback_code: object | None = None,
) -> OperatorBlockViewV1 | None:
    code = recovery_code_for_step(step)
    if code is None and fallback_code is not None:
        code = normalize_recovery_code(fallback_code)
    if code is None:
        return None
    definition = OPERATOR_RECOVERY_CATALOG[code]
    recovery = getattr(step, "recovery", None)
    retry_at = reevaluate_at or getattr(recovery, "retry_at", None)
    return OperatorBlockViewV1(
        code=code,
        message=definition.message,
        repair_owner=definition.repair_owner,
        reevaluate_at=retry_at,
        recovery_link=recovery_link,
    )


def recovery_href_for_code(code: object, *, task_key: str | None = None) -> str | None:
    raw = _value(code)
    try:
        stable_code = OperatorRecoveryCode(raw)
    except (TypeError, ValueError):
        return None
    default = OPERATOR_RECOVERY_CATALOG[stable_code].default_recovery_href
    if default is not None:
        return default
    match = None if task_key is None else _TASK_KEY.fullmatch(task_key)
    if match is None:
        return "/operator-next"
    return (
        f"/operator-next/{match.group('lane')}/"
        f"{match.group('business_key')}"
    )


__all__ = [
    "OPERATOR_RECOVERY_CATALOG",
    "OperatorRecoveryDefinition",
    "normalize_recovery_code",
    "recovery_block_for_step",
    "recovery_code_for_step",
    "recovery_href_for_code",
]
