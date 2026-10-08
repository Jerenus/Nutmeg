#!/usr/bin/env python3
"""Deterministic guardrails around Nutmeg's scheduled AM decision stage."""

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
DEFAULT_OPERATION_STATE_FILE = ROOT / ".nutmeg-data" / "state" / "scheduler-operation-events.json"


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


EMPTY_BOARD_MARK = ("Sporttery calculator empty (not a WAF block): "
                    "match list 0 Selling / 0 not yet on sale")
"""体彩列表完全为空（0 在售、0 未开售、不是 WAF）＝当天没有竞彩（假期/停赛）。"""
NOTHING_ON_SALE = re.compile(
    r"Sporttery calculator empty \(not a WAF block\): match list 0 Selling / \d+ not yet on sale")
"""体彩赛程接口说一场都没开售（含完全为空）＝合法空盘：此刻没有可买的东西。"""


def _only_empty_board(failed_steps: list[dict]) -> bool:
    """唯一的失败是「体彩一场都没开售」→ 合法空盘，不是故障。

    2026-10-02：列表完全为空（国庆）。2026-10-05 扩到「0 在售 / N 未开售」：周一板 11:00
    才开售、假期次日板提前挂出，这时体彩赛程接口本身就是权威答案，重试与告警换不来任何东西；
    开售后 11:00/14:00 备料里的入库与 17:15 刷新会抓到。有场次在售而计算器为空（抖动）、
    赛程接口也拿不到（WAF）、或有任何其它失败，仍按故障处理。"""
    return bool(failed_steps) and all(
        NOTHING_ON_SALE.search(str(item.get("message") or "")) for item in failed_steps
    )


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
    if failed_steps and _only_empty_board(failed_steps):
        payload["empty_board"] = True
        return payload
    if result.returncode != 0 or payload.get("status") != "succeeded" or failed_steps:
        detail = "; ".join(
            f"{item.get('label')}: {item.get('message')}" for item in failed_steps
        ) or f"exit={result.returncode} status={payload.get('status')}"
        raise SchedulerError(f"{stage} degraded: {detail}")
    return payload


def run_strict(
    stage: str,
    run_date: str,
    output_dir: Path,
    *,
    operation_state_file: Path = DEFAULT_OPERATION_STATE_FILE,
) -> None:
    try:
        command = ["uv", "run", "nutmeg", f"decision-{stage}", "--run-date", run_date,
                   "--output-dir", str(output_dir), "--format", "json"]
        result = _run(command)
        payload = _assert_strict_success(result, stage)
        if payload.get("empty_board"):
            _record_operation_success(stage, run_date, operation_state_file)
            print(f"NUTMEG_OK stage={stage} run_date={run_date} "
                  "empty_board（体彩无在售场次：假期或尚未开售，合法空盘）")
            return
        build_context(run_date, output_dir)
    except Exception as exc:
        error = exc if isinstance(exc, SchedulerError) else SchedulerError(str(exc))
        _record_operation_failure(stage, run_date, _safe_summary(str(error)), operation_state_file)
        if error is exc:
            raise
        raise error from exc
    _record_operation_success(stage, run_date, operation_state_file)
    print(f"NUTMEG_OK stage={stage} run_date={run_date}")


def build_context(run_date: str, output_dir: Path) -> Path:
    """当日板面上下文 ``daily/<日>/scheduler-context.json``（17:15 run-strict 与 OpenClaw
    08:10 / 12:30 命令作业都会重写；``day_runs`` 只读它的 ``generated_at``）。

    2026-10-08：删掉「昨日」整块——它聚合的 reads/tickets/settlements.jsonl 最后一行停在
    08-24（结算早已在内核，昨日结算看 ``decision-report-v2-<昨日>.md``），settle 日志与
    calibration-panel 也都没有写入者了，十月里每天都是 0 / 空串 / 七月的旧日志尾巴。
    """
    previous_date = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
    decision_dir = output_dir / "decision"
    day_dir = output_dir / "daily" / run_date
    day_dir.mkdir(parents=True, exist_ok=True)

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

    regime_path = day_dir / "day-regime.json"

    context = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_date": run_date,
        "previous_date": previous_date,
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
    strict.add_argument("--stage", choices=("am",), required=True)
    strict.add_argument("--run-date")

    context = subparsers.add_parser("build-context")
    context.add_argument("--run-date")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    try:
        if args.action == "run-strict":
            run_strict(args.stage, _run_date(args.run_date), output_dir)
        elif args.action == "build-context":
            build_context(_run_date(args.run_date), output_dir)
    except SchedulerError as exc:
        print(f"NUTMEG_FAILED {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
