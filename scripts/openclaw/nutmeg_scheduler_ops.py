#!/usr/bin/env python3
"""Deterministic guardrails around Nutmeg's scheduled decision pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / ".nutmeg-data" / "jczq"
DEFAULT_LOG_DIR = ROOT / ".nutmeg-data" / "logs"
DEFAULT_OPERATION_STATE_FILE = ROOT / ".nutmeg-data" / "state" / "scheduler-operation-events.json"
VALID_MARKETS = {"had", "hhad", "crs", "ttg"}
VALID_BUCKETS = {"main", "hedge", "draw", "parlay"}


class SchedulerError(RuntimeError):
    pass


def _run_date(value: str | None) -> str:
    return value or date.today().isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SchedulerError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"invalid JSON: {path}: {exc}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchedulerError(f"invalid JSONL: {path}:{number}: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _date_from_value(value: Any) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result


def _assert_strict_success(
    result: subprocess.CompletedProcess[str], stage: str
) -> dict[str, Any]:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"{stage} returned invalid structured JSON") from exc
    if not isinstance(payload, dict):
        raise SchedulerError(f"{stage} returned a non-object structured result")
    failed_steps = [
        item for item in payload.get("steps", [])
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    if result.returncode != 0 or payload.get("status") != "succeeded" or failed_steps:
        detail = "; ".join(
            f"{item.get('label')}: {item.get('message')}" for item in failed_steps
        ) or f"exit={result.returncode} status={payload.get('status')}"
        raise SchedulerError(f"{stage} degraded: {detail}")
    return payload


def _assert_plain_success(result: subprocess.CompletedProcess[str], stage: str) -> None:
    if result.returncode != 0:
        raise SchedulerError(f"{stage} failed: exit={result.returncode}")


def run_strict(
    stage: str,
    run_date: str,
    output_dir: Path,
    *,
    operation_state_file: Path = DEFAULT_OPERATION_STATE_FILE,
) -> None:
    try:
        # A missing decision is an upstream failure, never an implicit abstention.
        if stage == "close":
            validate_preclose(run_date, output_dir)

        command = ["uv", "run", "nutmeg", f"decision-{stage}", "--run-date", run_date,
                   "--output-dir", str(output_dir)]
        if stage in {"close", "settle"}:
            command.extend(["--dispatch-telegram", "--no-dry-run"])
        command.extend(["--format", "json"])
        result = _run(command)
        _assert_strict_success(result, stage)
        if stage == "am":
            build_context(run_date, output_dir, DEFAULT_LOG_DIR)
        elif stage == "settle":
            build_context(date.today().isoformat(), output_dir, DEFAULT_LOG_DIR)
    except Exception as exc:
        error = exc if isinstance(exc, SchedulerError) else SchedulerError(str(exc))
        summary = _user_safe_failure_summary(stage, str(error))
        _record_operation_failure(stage, run_date, summary, operation_state_file)
        if error is exc:
            raise
        raise error from exc
    _record_operation_success(stage, run_date, operation_state_file)
    print(f"NUTMEG_OK stage={stage} run_date={run_date}")


def retry_settlement(days: list[int], output_dir: Path) -> None:
    settled_at = datetime.now().astimezone().isoformat(timespec="seconds")
    completed: list[str] = []
    for days_ago in days:
        run_date = (date.today() - timedelta(days=days_ago)).isoformat()
        command = [
            "uv", "run", "nutmeg", "decision-reconcile",
            "--run-date", run_date,
            "--output-dir", str(output_dir),
            "--settled-at", settled_at,
        ]
        result = _run(command)
        _assert_plain_success(result, f"reconcile-{run_date}")
        completed.append(run_date)
    build_context(date.today().isoformat(), output_dir, DEFAULT_LOG_DIR)
    print(f"NUTMEG_OK settlement_retry={','.join(completed)} dispatch=false")


def build_context(run_date: str, output_dir: Path, log_dir: Path) -> Path:
    previous_date = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
    decision_dir = output_dir / "decision"
    day_dir = output_dir / "daily" / run_date
    day_dir.mkdir(parents=True, exist_ok=True)

    reads = _read_jsonl(decision_dir / "reads.jsonl")
    tickets = _read_jsonl(decision_dir / "tickets.jsonl")
    settlements = _read_jsonl(decision_dir / "settlements.jsonl")
    ref_dates: dict[str, str] = {}
    for row in reads:
        match_date = str(row.get("match_id", ""))[2:12]
        ref_dates[str(row.get("read_id", ""))] = match_date
    for row in tickets:
        ref_dates[str(row.get("ticket_id", ""))] = _date_from_value(row.get("made_at"))

    previous_settlements = [
        row for row in settlements
        if ref_dates.get(str(row.get("ref_id", ""))) == previous_date
    ]
    brier_values = [
        float(row["brier"]) for row in previous_settlements
        if isinstance(row.get("brier"), (int, float))
    ]
    clv_values = [
        float(row["clv_pp"]) for row in previous_settlements
        if isinstance(row.get("clv_pp"), (int, float))
    ]
    pnl_values = [
        float(row["pnl_yuan"]) for row in previous_settlements
        if isinstance(row.get("pnl_yuan"), (int, float))
    ]

    markets_path = day_dir / "sporttery_markets.json"
    markets = _read_json(markets_path) if markets_path.exists() else {}
    fixtures: list[dict[str, Any]] = []
    if isinstance(markets, dict):
        for group in markets.get("matchInfoList", []):
            if not isinstance(group, dict):
                continue
            for match in group.get("subMatchList", []):
                if not isinstance(match, dict):
                    continue
                fixtures.append({
                    "business_date": match.get("businessDate"),
                    "match_num": match.get("matchNumStr") or match.get("matchNum"),
                    "league": match.get("leagueAbbName") or match.get("leagueAllName"),
                    "home": match.get("homeTeamAbbName") or match.get("homeTeamAllName"),
                    "away": match.get("awayTeamAbbName") or match.get("awayTeamAllName"),
                    "match_time": match.get("matchTime"),
                    "status": match.get("matchStatus"),
                })

    # 判读前置知识:当日板面涉及的联赛/球队画像 + 别名覆盖审计。
    # 画像不注入 = 建了也读不到(profile_notes 曾整整一个月零消费者);
    # 别名缺口不注入 = 欧赔锚静默丢失(8/04 全板面丢锚)。导入失败只降级,不拖垮 context。
    entity_profiles: dict[str, Any] | None = None
    alias_audit: dict[str, Any] | None = None
    try:
        from nutmeg.decision.alias_audit import audit_board
        from nutmeg.decision.entities import profiles_for_board
        from nutmeg.decision.store import DecisionStore

        store = DecisionStore(decision_dir)
        entity_profiles = profiles_for_board(
            store,
            [str(f.get("league") or "") for f in fixtures],
            [str(f.get(side) or "") for f in fixtures for side in ("home", "away")],
        )
        alias_audit = audit_board(markets) if isinstance(markets, dict) else None
    except Exception as exc:  # noqa: BLE001 — 上下文构建永不因附加信息失败
        print(f"NUTMEG_CONTEXT_WARN entity_profiles_unavailable={exc}", file=sys.stderr)

    settle_out = log_dir / "decision.settle.out.log"
    settle_err = log_dir / "decision.settle.err.log"
    settle_lines = settle_out.read_text(encoding="utf-8", errors="replace").splitlines()[-40:] \
        if settle_out.exists() else []
    error_text = settle_err.read_text(encoding="utf-8", errors="replace")[-4000:] \
        if settle_err.exists() else ""
    calibration_path = decision_dir / f"calibration-panel-{previous_date}.md"
    calibration = calibration_path.read_text(encoding="utf-8", errors="replace")[-16000:] \
        if calibration_path.exists() else ""
    regime_path = day_dir / "day-regime.json"

    context = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_date": run_date,
        "previous_date": previous_date,
        "previous_day": {
            "settlement_count": len(previous_settlements),
            "read_settlement_count": sum(
                row.get("ref_type") == "read" for row in previous_settlements
            ),
            "ticket_settlement_count": sum(
                row.get("ref_type") == "ticket" for row in previous_settlements
            ),
            "average_brier": _mean(brier_values),
            "average_clv_pp": _mean(clv_values),
            "clv_observation_count": len(clv_values),
            "ticket_pnl_yuan": round(sum(pnl_values), 2),
            "settle_log_tail": settle_lines,
            "settle_error_tail": error_text,
            "calibration_panel": calibration,
        },
        "current_day": {
            "day_regime": _read_json(regime_path) if regime_path.exists() else None,
            "market_last_update": (
                markets.get("lastUpdateTime") if isinstance(markets, dict) else None
            ),
            "market_total_count": markets.get("totalCount") if isinstance(markets, dict) else None,
            "fixtures": fixtures,
            "entity_profiles": entity_profiles,
            "alias_audit": alias_audit,
        },
    }
    context_path = day_dir / "scheduler-context.json"
    context_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"NUTMEG_CONTEXT_OK path={context_path} fixtures={len(fixtures)}")
    return context_path


def _validate_handoff(run_date: str, output_dir: Path) -> tuple[dict[str, Any], Path]:
    day_dir = output_dir / "daily" / run_date
    handoff_path = day_dir / "nutmeg-handoff.json"
    handoff = _read_json(handoff_path)
    if not isinstance(handoff, dict):
        raise SchedulerError("nutmeg-handoff.json must be an object")
    if handoff.get("run_date") != run_date:
        raise SchedulerError("handoff run_date does not match the scheduled date")
    if handoff.get("status") != "frozen":
        raise SchedulerError("handoff is not frozen")
    if handoff.get("position") not in {"ready", "abstain"}:
        raise SchedulerError("handoff position must be ready or abstain")
    if not str(handoff.get("summary", "")).strip():
        raise SchedulerError("handoff summary is required")
    return handoff, day_dir


def _validate_legs(legs: Any) -> list[str]:
    if not isinstance(legs, list):
        raise SchedulerError("legs.json must contain an array")
    errors: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    for index, leg in enumerate(legs):
        label = f"legs[{index}]"
        if not isinstance(leg, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in ("match_id", "market", "selection", "odds", "bucket"):
            if leg.get(field) in (None, ""):
                errors.append(f"{label}.{field} is required")
        market = leg.get("market")
        if market not in VALID_MARKETS:
            errors.append(f"{label}.market is invalid")
        if leg.get("bucket") not in VALID_BUCKETS:
            errors.append(f"{label}.bucket is invalid")
        try:
            if float(leg.get("odds", 0)) <= 1:
                errors.append(f"{label}.odds must be greater than 1")
        except (TypeError, ValueError):
            errors.append(f"{label}.odds must be numeric")
        if market == "hhad" and not isinstance(leg.get("line"), (int, float)):
            errors.append(f"{label}.line is required for hhad")
        key = (leg.get("match_id"), market, leg.get("selection"), leg.get("bucket"))
        if key in seen:
            errors.append(f"{label} duplicates another leg")
        seen.add(key)
    return errors


def validate_preclose(run_date: str, output_dir: Path) -> None:
    handoff, day_dir = _validate_handoff(run_date, output_dir)
    position = handoff["position"]
    legs_path = day_dir / "legs.json"
    legs = _read_json(legs_path) if legs_path.exists() else []
    errors = _validate_legs(legs)

    if position == "ready" and not legs:
        errors.append("ready position requires at least one leg")
    if position == "abstain":
        if legs:
            errors.append("abstain position requires an empty or absent legs.json")
        if not str(handoff.get("explicit_empty_reason", "")).strip():
            errors.append("abstain position requires explicit_empty_reason")

    if errors:
        raise SchedulerError("; ".join(errors))
    print(
        f"NUTMEG_GATE_OK run_date={run_date} position={position} "
        f"legs={len(legs)} status=frozen"
    )


def verify_close(run_date: str, output_dir: Path, log_dir: Path) -> None:
    _validate_handoff(run_date, output_dir)
    report = output_dir / "daily" / run_date / f"decision-report-{run_date}.pdf"
    if not report.exists() or report.stat().st_size == 0:
        raise SchedulerError(f"missing or empty report: {report}")

    del log_dir
    if not _has_sent_notification(
        kind="decision.close.report",
        business_key=run_date,
        stage="close",
    ):
        raise SchedulerError("notification ledger does not confirm close report delivery")
    print(
        f"NUTMEG_CLOSE_OK run_date={run_date} report_bytes={report.stat().st_size} "
        "telegram=dispatched"
    )


def _user_safe_failure_summary(stage: str, error: str) -> str:
    if stage == "close" and any(
        marker in error
        for marker in (
            "nutmeg-handoff.json",
            "handoff is not frozen",
            "ready position",
            "abstain position",
        )
    ):
        return "今日决策未完成，收盘已安全停止；系统未将流程失败记为空仓。"
    return _safe_summary(error)


def _record_operation_failure(
    stage: str,
    run_date: str,
    error: str,
    state_file: Path,
) -> None:
    key = f"{stage}:{run_date}"
    error = _safe_summary(error)
    state = _load_operation_state(state_file)
    state[key] = {"status": "failed", "error": error, "updated_at": _now()}
    _write_operation_state(state_file, state)
    if not _is_notification_transport_failure(error):
        _publish_operation_event(
            kind="operations.failure",
            stage=stage,
            run_date=run_date,
            summary=error,
        )


def _record_operation_success(stage: str, run_date: str, state_file: Path) -> None:
    key = f"{stage}:{run_date}"
    state = _load_operation_state(state_file)
    previous = state.get(key)
    if isinstance(previous, dict) and previous.get("status") == "failed":
        _publish_operation_event(
            kind="operations.recovered",
            stage=stage,
            run_date=run_date,
            summary=f"{stage} recovered after a previous failed run",
        )
    state[key] = {"status": "succeeded", "updated_at": _now()}
    _write_operation_state(state_file, state)


def _publish_operation_event(
    *,
    kind: str,
    stage: str,
    run_date: str,
    summary: str,
):
    from nutmeg.notifications.models import NotificationRequest, semantic_fingerprint
    from nutmeg.notifications.wiring import build_notification_service

    summary = _safe_summary(summary)
    request = NotificationRequest.text(
        kind=kind,
        business_key=f"{stage}:{run_date}",
        stage=stage,
        semantic_fingerprint=semantic_fingerprint(
            {"kind": kind, "stage": stage, "run_date": run_date, "summary": summary}
        ),
        subject=f"Nutmeg scheduler {stage}: {kind.rsplit('.', 1)[-1]}",
        text=summary,
        metadata={"stage": stage, "run_date": run_date},
    )
    return build_notification_service().publish(request)


def _has_sent_notification(*, kind: str, business_key: str, stage: str) -> bool:
    from datetime import UTC, datetime

    from nutmeg.notifications.wiring import build_notification_service

    notifications = build_notification_service().repository.list_recent(
        datetime(2000, 1, 1, tzinfo=UTC)
    )
    return any(
        item.kind == kind
        and item.business_key == business_key
        and item.stage == stage
        and item.status.value == "sent"
        for item in notifications
    )


def _load_operation_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = _read_json(path)
    return value if isinstance(value, dict) else {}


def _write_operation_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_notification_transport_failure(error: str) -> bool:
    normalized = error.casefold()
    return "notification" in normalized and any(
        marker in normalized for marker in ("telegram", "delivery", "recipient", "provider")
    )


def _safe_summary(value: str) -> str:
    redacted = re.sub(r"/bot[^/\s]+", "/bot***", value)
    redacted = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password)[A-Z0-9_]*\s*=\s*)[^&\s]+",
        r"\1***",
        redacted,
    )
    return redacted[:2000]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    subparsers = parser.add_subparsers(dest="action", required=True)

    strict = subparsers.add_parser("run-strict")
    strict.add_argument("--stage", choices=("am", "close", "settle"), required=True)
    strict.add_argument("--run-date")

    retry = subparsers.add_parser("retry-settlement")
    retry.add_argument("--days", type=int, nargs="+", default=[1, 2])

    preclose = subparsers.add_parser("validate-preclose")
    preclose.add_argument("--run-date")

    close = subparsers.add_parser("verify-close")
    close.add_argument("--run-date")
    close.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)

    context = subparsers.add_parser("build-context")
    context.add_argument("--run-date")
    context.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    try:
        if args.action == "run-strict":
            run_strict(args.stage, _run_date(args.run_date), output_dir)
        elif args.action == "retry-settlement":
            retry_settlement(args.days, output_dir)
        elif args.action == "validate-preclose":
            validate_preclose(_run_date(args.run_date), output_dir)
        elif args.action == "verify-close":
            verify_close(_run_date(args.run_date), output_dir, args.log_dir.resolve())
        elif args.action == "build-context":
            build_context(_run_date(args.run_date), output_dir, args.log_dir.resolve())
    except SchedulerError as exc:
        print(f"NUTMEG_FAILED {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
