"""Bounded read-only ownership diagnostics for the operator maintenance surface."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Literal

from nutmeg.product.operator_contracts import (
    OperatorMaintenanceResponseV1,
    OperatorStage,
    SchedulerOwnershipClaimV1,
    SchedulerStageSummaryV1,
    TelegramOwnerStatusV1,
    TelegramTransportStatusV1,
)

_MAX_OUTPUT_BYTES = 262_144
_PROBE_TIMEOUT_SECONDS = 5
_OPENCLAW_CRON_ARGV = ["openclaw", "cron", "list", "--all", "--json"]
_OPENCLAW_TELEGRAM_ARGV = [
    "openclaw",
    "channels",
    "status",
    "--channel",
    "telegram",
    "--json",
]
_OPENCLAW_NAMES = {
    "Nutmeg-AM数据入库": OperatorStage.JCZQ_AM,
    "Nutmeg-临场数据刷新": OperatorStage.JCZQ_AM,
    "Nutmeg-每日最终决策": OperatorStage.JCZQ_DECISION,
    "Nutmeg-最终决策受限补跑": OperatorStage.JCZQ_DECISION_RECOVERY,
    "Nutmeg-收盘前闸门": OperatorStage.JCZQ_PRECLOSE_CHECK,
    "Nutmeg-收盘": OperatorStage.JCZQ_CLOSE,
    "Nutmeg-收盘交付确认": OperatorStage.JCZQ_CLOSE_VERIFY,
    "Nutmeg-昨日结算": OperatorStage.JCZQ_SETTLE,
    "Nutmeg-D1D2补结算": OperatorStage.JCZQ_SETTLEMENT_RETRY,
}
_LAUNCHD_STAGES = {
    "com.nutmeg.decision.am": OperatorStage.JCZQ_AM,
    "com.nutmeg.decision.close": OperatorStage.JCZQ_CLOSE,
    "com.nutmeg.decision.settle": OperatorStage.JCZQ_SETTLE,
    "com.nutmeg.zucai.prep": OperatorStage.ZUCAI_PREP,
    "com.nutmeg.zucai.prep-revision": OperatorStage.ZUCAI_PREP_REVISION,
    "com.nutmeg.zucai.afternoon": OperatorStage.ZUCAI_AFTERNOON,
    "com.nutmeg.zucai.revision": OperatorStage.ZUCAI_REVISION,
}
_LAST_STATUSES = {"ok", "error", "success", "failed", "skipped", "running"}
_SCHEDULER_STAGE_VALUES = {
    "am": OperatorStage.JCZQ_AM,
    "close": OperatorStage.JCZQ_CLOSE,
    "settle": OperatorStage.JCZQ_SETTLE,
}
_SCHEDULER_COMMANDS = {
    "validate-preclose": OperatorStage.JCZQ_PRECLOSE_CHECK,
    "verify-close": OperatorStage.JCZQ_CLOSE_VERIFY,
    "retry-settlement": OperatorStage.JCZQ_SETTLEMENT_RETRY,
}
_LAUNCHD_STATES = {
    "running",
    "not running",
    "waiting",
    "spawn scheduled",
    "throttled",
}


class _DiagnosticFailure(RuntimeError):
    pass


def _default_runner(argv: list[str], **kwargs: object):
    return subprocess.run(argv, **kwargs)  # noqa: S603 - argv is closed in this module


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _milliseconds(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _DiagnosticFailure("invalid timestamp")
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise _DiagnosticFailure("invalid timestamp") from error


def _iso_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 100:
        raise _DiagnosticFailure("invalid heartbeat timestamp")
    try:
        return _aware(datetime.fromisoformat(value), "heartbeat timestamp")
    except ValueError as error:
        raise _DiagnosticFailure("invalid heartbeat timestamp") from error


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _DiagnosticFailure("invalid diagnostic object")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _DiagnosticFailure("invalid diagnostic list")
    return value


def _safe_status(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _LAST_STATUSES:
        raise _DiagnosticFailure("unknown scheduler status")
    return value


def _option_pairs_are_allowed(tokens: Sequence[str], allowed: set[str]) -> bool:
    index = 0
    while index < len(tokens):
        option = tokens[index]
        if option not in allowed or index + 1 >= len(tokens):
            return False
        index += 2
    return True


def _scheduler_tail_stage(tokens: Sequence[str]) -> OperatorStage:
    script_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if token.endswith("scripts/openclaw/nutmeg_scheduler_ops.py")
            or token == "nutmeg_scheduler_ops.py"
        ),
        None,
    )
    if script_index is None:
        raise _DiagnosticFailure("scheduler script was not found")
    tail = list(tokens[script_index + 1 :])
    if tail[:1] == ["--output-dir"] and len(tail) >= 3:
        tail = tail[2:]
    if not tail:
        raise _DiagnosticFailure("scheduler command is missing")
    command = tail[0]
    arguments = tail[1:]
    if command == "run-strict":
        if len(arguments) < 2 or arguments[:1] != ["--stage"]:
            raise _DiagnosticFailure("run-strict stage is missing")
        stage = _SCHEDULER_STAGE_VALUES.get(arguments[1])
        if stage is None or not _option_pairs_are_allowed(arguments[2:], {"--run-date"}):
            raise _DiagnosticFailure("run-strict arguments are unknown")
        return stage
    stage = _SCHEDULER_COMMANDS.get(command)
    allowed = {
        "validate-preclose": {"--run-date"},
        "verify-close": {"--run-date", "--log-dir"},
        "retry-settlement": {"--days"},
    }.get(command)
    if stage is None or allowed is None:
        raise _DiagnosticFailure("scheduler command is unknown")
    if command == "retry-settlement":
        if not arguments:
            return stage
        if (
            len(arguments) < 2
            or arguments[0] != "--days"
            or not all(item.isdigit() for item in arguments[1:])
        ):
            raise _DiagnosticFailure("retry-settlement arguments are unknown")
        return stage
    if not _option_pairs_are_allowed(arguments, allowed):
        raise _DiagnosticFailure("scheduler arguments are unknown")
    return stage


def _decision_settle_stage(tokens: Sequence[str]) -> OperatorStage:
    index = tokens.index("decision-settle")
    arguments = list(tokens[index + 1 :])
    valued = {"--run-date", "--output-dir", "--issue", "--zucai-dir", "--format"}
    flags = {"--dispatch-telegram", "--dry-run", "--no-dry-run"}
    cursor = 0
    while cursor < len(arguments):
        option = arguments[cursor]
        if option in flags:
            cursor += 1
        elif option in valued and cursor + 1 < len(arguments):
            cursor += 2
        else:
            raise _DiagnosticFailure("decision-settle arguments are unknown")
    return OperatorStage.JCZQ_SETTLE


def _argv_stage(value: object) -> OperatorStage | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and 0 < len(item) <= 16_384 for item in value)
    ):
        raise _DiagnosticFailure("invalid scheduler argv")
    tokens = list(value)
    if len(tokens) == 3 and tokens[:2] in (["sh", "-lc"], ["/bin/sh", "-lc"]):
        markers = ("nutmeg_scheduler_ops.py", "decision-settle")
        if not any(marker in tokens[2] for marker in markers):
            return None
        return _shell_stage(tokens[2])
    joined = " ".join(tokens)
    if "nutmeg_scheduler_ops.py" in joined:
        return _scheduler_tail_stage(tokens)
    if "decision-settle" in tokens:
        return _decision_settle_stage(tokens)
    return None


def _shell_segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.commenters = ""
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as error:
        raise _DiagnosticFailure("shell scheduler argv is malformed") from error
    segments: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "$" and index + 1 < len(tokens) and tokens[index + 1] == "(":
            depth = 1
            index += 2
            while index < len(tokens) and depth:
                depth += tokens[index] == "("
                depth -= tokens[index] == ")"
                index += 1
            if depth:
                raise _DiagnosticFailure("shell substitution is malformed")
            current.append("$()")
            continue
        if token in {";", "&&", "||", "|"}:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
        index += 1
    if current:
        segments.append(current)
    return segments


def _is_safe_shell_prelude(tokens: Sequence[str]) -> bool:
    return list(tokens) in (["set", "-a"], ["set", "+a"], ["source", ".env"])


def _is_safe_build_context(tokens: Sequence[str]) -> bool:
    script_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if token.endswith("scripts/openclaw/nutmeg_scheduler_ops.py")
            or token == "nutmeg_scheduler_ops.py"
        ),
        None,
    )
    if script_index is None:
        return False
    tail = list(tokens[script_index + 1 :])
    return bool(
        tail
        and tail[0] == "build-context"
        and _option_pairs_are_allowed(tail[1:], {"--run-date", "--log-dir"})
    )


def _shell_stage(command: str) -> OperatorStage:
    stages: set[OperatorStage] = set()
    unknown_segments: list[list[str]] = []
    for segment in _shell_segments(command):
        if any(
            token.endswith("scripts/openclaw/nutmeg_scheduler_ops.py")
            or token == "nutmeg_scheduler_ops.py"
            for token in segment
        ):
            if _is_safe_build_context(segment):
                continue
            stages.add(_scheduler_tail_stage(segment))
        elif "decision-settle" in segment:
            stages.add(_decision_settle_stage(segment))
        elif not _is_safe_shell_prelude(segment):
            unknown_segments.append(segment)
    if len(stages) != 1 or unknown_segments:
        raise _DiagnosticFailure("shell scheduler command is ambiguous")
    return next(iter(stages))


class OperatorMaintenanceProbe:
    """Read current scheduler/Telegram health without accepting probe inputs."""

    def __init__(
        self,
        *,
        runner: Callable[..., object] = _default_runner,
        heartbeat_service=None,
        owner_mode: Literal["openclaw", "native_distinct_token"] = "openclaw",
    ) -> None:
        self._runner = runner
        self._heartbeat_service = heartbeat_service
        self._owner_mode = owner_mode

    def read(self, *, as_of: datetime) -> OperatorMaintenanceResponseV1:
        cutoff = _aware(as_of, "as_of")
        try:
            cron = self._json_probe(_OPENCLAW_CRON_ARGV)
            channels = self._json_probe(_OPENCLAW_TELEGRAM_ARGV)
            claims = self._cron_claims(cron)
            transport = self._telegram_transport(channels)
            claims.extend(self._launchd_claims())
            owner = self._telegram_owner(cutoff)
            active_counts = {
                stage: sum(claim.active and claim.stage is stage for claim in claims)
                for stage in OperatorStage
            }
            stages = [
                SchedulerStageSummaryV1(
                    stage=stage,
                    claim_count=active_counts[stage],
                    conflict=active_counts[stage] > 1,
                )
                for stage in OperatorStage
            ]
            return OperatorMaintenanceResponseV1(
                as_of=cutoff,
                diagnostic_state="available",
                claims=claims,
                stages=stages,
                telegram_owner=owner,
                telegram_transport=transport,
            )
        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
            ValueError,
            TypeError,
            RecursionError,
            _DiagnosticFailure,
        ):
            return self._unavailable(cutoff)

    def _run(self, argv: list[str]) -> bytes:
        completed = self._runner(
            argv,
            capture_output=True,
            check=False,
            shell=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        if getattr(completed, "returncode", 1) != 0:
            raise _DiagnosticFailure("diagnostic command failed")
        stdout = getattr(completed, "stdout", None)
        stderr = getattr(completed, "stderr", None)
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise _DiagnosticFailure("diagnostic command returned non-byte output")
        if len(stdout) > _MAX_OUTPUT_BYTES or len(stderr) > _MAX_OUTPUT_BYTES:
            raise _DiagnosticFailure("diagnostic command output exceeded limit")
        return stdout

    def _json_probe(self, argv: list[str]) -> dict[str, object]:
        try:
            value = json.loads(self._run(argv).decode("utf-8"))
        except json.JSONDecodeError as error:
            raise _DiagnosticFailure("diagnostic JSON is malformed") from error
        return _mapping(value)

    def _cron_claims(self, payload: dict[str, object]) -> list[SchedulerOwnershipClaimV1]:
        jobs = _list(payload.get("jobs"))
        if len(jobs) > 1_000:
            raise _DiagnosticFailure("too many scheduler jobs")
        claims: list[SchedulerOwnershipClaimV1] = []
        for raw_job in jobs:
            job = _mapping(raw_job)
            name = job.get("name")
            if not isinstance(name, str) or not name or len(name) > 200:
                raise _DiagnosticFailure("scheduler job name is invalid")
            enabled = job.get("enabled")
            if not isinstance(enabled, bool):
                raise _DiagnosticFailure("scheduler enabled state is invalid")
            named_stage = _OPENCLAW_NAMES.get(name)
            if name.startswith("Nutmeg-") and named_stage is None:
                raise _DiagnosticFailure("unknown Nutmeg scheduler name")
            raw_payload = job.get("payload", {})
            job_payload = _mapping(raw_payload)
            argv_stage = _argv_stage(job_payload.get("argv"))
            if named_stage is not None and argv_stage is not None and named_stage is not argv_stage:
                raise _DiagnosticFailure("scheduler name and argv disagree")
            stage = argv_stage or named_stage
            if stage is None:
                continue
            state = job.get("state", {})
            state_mapping = _mapping(state) if state is not None else {}
            last_at = job.get("lastRunAtMs", state_mapping.get("lastRunAtMs"))
            last_status = job.get(
                "lastRunStatus",
                state_mapping.get("lastRunStatus", state_mapping.get("lastStatus")),
            )
            claims.append(
                SchedulerOwnershipClaimV1(
                    owner_kind="openclaw",
                    business_label=name,
                    stage=stage,
                    enabled=enabled,
                    last_run_at=_milliseconds(last_at),
                    last_status=_safe_status(last_status),
                )
            )
        return claims

    def _launchd_claims(self) -> list[SchedulerOwnershipClaimV1]:
        claims: list[SchedulerOwnershipClaimV1] = []
        uid = os.getuid()
        for label, stage in _LAUNCHD_STAGES.items():
            stdout = self._run(["launchctl", "print", f"gui/{uid}/{label}"])
            text = stdout.decode("utf-8")
            header = f"gui/{uid}/{label} = {{"
            if not text.startswith(header) or not text.rstrip().endswith("}"):
                raise _DiagnosticFailure("launchd label is unknown")
            state_match = re.search(r"^\s*state = (.+)$", text, flags=re.MULTILINE)
            exit_match = re.search(r"^\s*last exit code = (-?\d+)$", text, flags=re.MULTILINE)
            if state_match is None or state_match.group(1) not in _LAUNCHD_STATES:
                raise _DiagnosticFailure("launchd state is invalid")
            status = state_match.group(1)
            if exit_match is not None:
                status = f"{status}; exit {int(exit_match.group(1))}"
            claims.append(
                SchedulerOwnershipClaimV1(
                    owner_kind="launchd",
                    business_label=label,
                    stage=stage,
                    loaded=True,
                    last_status=status,
                )
            )
        return claims

    @staticmethod
    def _telegram_transport(payload: dict[str, object]) -> TelegramTransportStatusV1:
        channel_accounts = _mapping(payload.get("channelAccounts"))
        accounts = _list(channel_accounts.get("telegram"))
        selected = [
            account for item in accounts if (account := _mapping(item)).get("accountId") == "nutmeg"
        ]
        if len(selected) != 1:
            raise _DiagnosticFailure("telegram:nutmeg account is unavailable")
        account = selected[0]
        facts = [account.get(name) for name in ("configured", "running", "connected")]
        if not all(isinstance(value, bool) for value in facts):
            raise _DiagnosticFailure("Telegram transport state is invalid")
        return TelegramTransportStatusV1(
            state="available",
            configured=facts[0],
            running=facts[1],
            connected=facts[2],
            last_connected_at=_milliseconds(account.get("lastConnectedAt")),
            last_started_at=_milliseconds(account.get("lastStartAt")),
            last_transport_activity_at=_milliseconds(account.get("lastTransportActivityAt")),
        )

    def _telegram_owner(self, cutoff: datetime) -> TelegramOwnerStatusV1:
        if self._heartbeat_service is None:
            return TelegramOwnerStatusV1(
                owner_mode="unavailable",
                configured=False,
                heartbeat_state="unavailable",
                confirmation_available=False,
                blocking_code="telegram_owner_unavailable",
                recovery_label="配置并启动 Telegram 确认处理器",
            )
        status = self._heartbeat_service.status(as_of=cutoff)
        blocking_code = getattr(status, "blocking_code", None)
        available = getattr(status, "available", None)
        configured = getattr(status, "configured", None)
        if not isinstance(available, bool) or not isinstance(configured, bool):
            raise _DiagnosticFailure("Telegram owner status is invalid")
        state_by_code = {
            "telegram_owner_missing": "missing",
            "telegram_owner_heartbeat_expired": "expired",
            "telegram_owner_clock_skew": "clock_skew",
            "telegram_update_owner_conflict": "conflict",
        }
        if available:
            if blocking_code is not None:
                raise _DiagnosticFailure("Telegram owner status is inconsistent")
            heartbeat_state = "available"
            owner_mode: str = self._owner_mode
            recovery = None
        else:
            heartbeat_state = state_by_code.get(blocking_code)
            if heartbeat_state is None:
                raise _DiagnosticFailure("Telegram owner blocking code is unknown")
            owner_mode = "conflict" if heartbeat_state == "conflict" else self._owner_mode
            recovery = "检查 Telegram 确认处理器状态"
        return TelegramOwnerStatusV1(
            owner_mode=owner_mode,
            configured=configured,
            last_heartbeat_at=_iso_datetime(getattr(status, "last_heartbeat_at", None)),
            heartbeat_state=heartbeat_state,
            confirmation_available=available,
            blocking_code=blocking_code,
            recovery_label=recovery,
        )

    @staticmethod
    def _unavailable(cutoff: datetime) -> OperatorMaintenanceResponseV1:
        return OperatorMaintenanceResponseV1(
            as_of=cutoff,
            diagnostic_state="diagnostic_unavailable",
            diagnostic_code="diagnostic_unavailable",
            claims=[],
            stages=[],
            telegram_owner=TelegramOwnerStatusV1(
                owner_mode="unavailable",
                configured=False,
                heartbeat_state="unavailable",
                confirmation_available=False,
                blocking_code="diagnostic_unavailable",
                recovery_label="修复只读维护诊断后重试",
            ),
            telegram_transport=TelegramTransportStatusV1(state="diagnostic_unavailable"),
            recovery_label="修复只读维护诊断后重试",
        )


__all__ = ["OperatorMaintenanceProbe"]
