#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH = ROOT / ".nutmeg-data" / "state" / "openclaw-router.lock"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_OPERATOR_INTAKE_ROOT = (
    Path(os.environ.get("NUTMEG_OPERATOR_INTAKE_ROOT", ROOT / ".nutmeg-data" / "intake"))
    .expanduser()
    .resolve()
)
SUPPORTED_ACTIONS = {
    "doctor",
    "status",
    "telegram-status",
    "seed-demo",
    "fixtures",
    "sync",
    "reference-refresh",
    "popular",
    "today",
    "snapshot",
    "odds",
    "visuals",
    "brief",
    "analyze",
    "value",
    "player",
    "daily",
    "zucai-report",
    "eval",
    "review",
    "prediction-record",
    "prediction-outcome",
    "operator-sale-ingest",
    "operator-schedule-check",
    "operator-evidence-ingest",
}

LEAGUE_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
FIXTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


class RouterError(ValueError):
    pass


class RouterRequest(NamedTuple):
    action: str
    options: argparse.Namespace


def parse_request(argv: list[str]) -> RouterRequest:
    action = _extract_action(argv)
    if action is not None and action not in SUPPORTED_ACTIONS:
        raise RouterError(f"Unsupported action `{action}`.")
    parser = _build_parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        raise RouterError("Invalid OpenClaw Nutmeg router arguments.") from exc
    if not getattr(options, "action", None):
        raise RouterError("Unsupported action. Run with --help to list supported actions.")
    _validate_options(options)
    return RouterRequest(action=options.action, options=options)


def build_command(request: RouterRequest) -> list[str]:
    options = request.options
    base = ["uv", "run", "nutmeg"]
    action = request.action

    if action == "doctor":
        return [*base, "doctor", "--format", "json"]
    if action == "status":
        return [*base, "agent-status", "--format", "json"]
    if action == "telegram-status":
        return [*base, "telegram-bot-status", "--format", "json"]
    if action == "seed-demo":
        return [*base, "seed-demo", "--league", options.league]
    if action == "fixtures":
        command = [*base, "fixtures", "--league", options.league, "--next", str(options.days)]
        if options.demo:
            command.append("--demo")
        return command
    if action == "sync":
        return [
            *base,
            "fixtures-sync",
            "--league",
            options.league,
            "--days",
            str(options.days),
            "--past-days",
            str(options.past_days),
        ]
    if action == "reference-refresh":
        return [
            *base,
            "reference-refresh",
            "--league",
            options.league,
            "--season",
            str(options.season),
        ]
    if action == "popular":
        command = [
            *base,
            "popular-matches",
            "--league",
            options.league,
            "--days",
            str(options.days),
            "--limit",
            str(options.limit),
            "--format",
            "json",
        ]
        if options.demo:
            command.append("--demo")
        if options.query:
            command.extend(["--query", options.query])
        return command
    if action == "today":
        command = [
            *base,
            "today-briefs",
            "--league",
            options.league,
            "--days",
            str(options.days),
            "--limit",
            str(options.limit),
            "--sort",
            options.sort,
            "--format",
            "json",
        ]
        if options.demo:
            command.append("--demo")
        if options.briefs:
            command.append("--briefs")
        if options.query:
            command.extend(["--query", options.query])
        return command
    if action == "snapshot":
        return [*base, "fixture-snapshot", "--fixture-id", options.fixture_id, "--format", "json"]
    if action == "odds":
        return [*base, "odds-snapshot", "--fixture-id", options.fixture_id, "--format", "json"]
    if action == "brief":
        return [
            *base,
            "match-brief",
            "--fixture-id",
            options.fixture_id,
            "--query",
            options.query,
            "--format",
            "json",
        ]
    if action == "analyze":
        return [
            *base,
            "analyze-match",
            "--fixture-id",
            options.fixture_id,
            "--query",
            options.query,
            "--format",
            "json",
        ]
    if action == "value":
        return [
            *base,
            "value-board",
            "--league",
            options.league,
            "--days",
            str(options.days),
            "--limit",
            str(options.limit),
            "--min-edge",
            str(options.min_edge),
            "--format",
            "json",
        ]
    if action == "player":
        return [
            *base,
            "player-profile",
            "--league",
            options.league,
            "--season",
            str(options.season),
            "--team",
            options.team,
            "--player",
            options.player,
            "--similar-limit",
            str(options.similar_limit),
            "--format",
            "json",
        ]
    if action == "visuals":
        return [
            *base,
            "tactical-visuals",
            "--fixture-id",
            options.fixture_id,
            "--output-dir",
            options.output_dir,
            "--format",
            "json",
        ]
    if action == "daily":
        command = [
            *base,
            "daily-run",
            "--league",
            options.league,
            "--days",
            str(options.days),
            "--limit",
            str(options.limit),
            "--query",
            options.query,
            "--format",
            "json",
        ]
        if options.live_sync:
            command.append("--live-sync")
        if options.briefs:
            command.append("--briefs")
        if options.dispatch_telegram:
            command.extend(["--dispatch-telegram", "--no-dry-run"])
        return command
    if action == "zucai-report":
        command = [
            *base,
            "zucai-report",
            "--issue-id",
            options.issue_id,
            "--output-dir",
            options.output_dir,
        ]
        if options.issue_file:
            command.extend(["--issue-file", options.issue_file])
        if options.odds_file:
            command.extend(["--odds-file", options.odds_file])
        if options.overrides_file:
            command.extend(["--overrides-file", options.overrides_file])
        if options.pdf:
            command.append("--pdf")
        if options.dispatch_telegram:
            command.extend(["--dispatch-telegram", "--no-dry-run"])
        command.extend(["--format", "json"])
        return command
    if action == "eval":
        return [*base, "eval-run", "--dataset", options.dataset, "--format", "json"]
    if action == "review":
        return [*base, "prediction-review", "--format", "json"]
    if action == "prediction-record":
        command = [
            *base,
            "prediction-record",
            "--fixture-id",
            options.fixture_id,
            "--league",
            options.league,
            "--home-team",
            options.home_team,
            "--away-team",
            options.away_team,
            "--home-probability",
            str(options.home_probability),
            "--draw-probability",
            str(options.draw_probability),
            "--away-probability",
            str(options.away_probability),
            "--pick",
            options.pick,
            "--format",
            "json",
        ]
        if options.notes:
            command.extend(["--notes", options.notes])
        return command
    if action == "prediction-outcome":
        return [
            *base,
            "prediction-outcome",
            "--prediction-id",
            str(options.prediction_id),
            "--actual",
            options.actual,
            "--format",
            "json",
        ]
    if action == "operator-sale-ingest":
        return [
            *base,
            "workflow",
            "ingest-official-sale",
            "--manifest",
            options.manifest,
            "--contract-version",
            options.contract_version,
        ]
    if action == "operator-schedule-check":
        return [
            *base,
            "workflow",
            "record-official-schedule-check",
            "--manifest",
            options.manifest,
            "--contract-version",
            options.contract_version,
        ]
    if action == "operator-evidence-ingest":
        return [
            *base,
            "workflow",
            "ingest-evidence",
            "--manifest",
            options.manifest,
        ]

    raise RouterError(f"Unsupported action `{action}`.")


def execute_request(
    request: RouterRequest,
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> dict[str, Any]:
    command = build_command(request)
    with _command_lock(lock_path):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=request.options.timeout,
        )
    payload = _parse_json_payload(completed.stdout)
    reply_text = render_reply_text(
        action=request.action,
        ok=completed.returncode == 0,
        payload=payload,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    return {
        "ok": completed.returncode == 0,
        "action": request.action,
        "command": command,
        "returncode": completed.returncode,
        "payload": payload,
        "reply_text": reply_text,
        "stdout": "" if payload is not None else completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        request = parse_request(argv)
        if request.options.print_command:
            envelope = {
                "ok": True,
                "action": request.action,
                "mode": "print-command",
                "command": build_command(request),
            }
            print(json.dumps(envelope, ensure_ascii=False, indent=2))
            return 0
        envelope = execute_request(request)
        if request.options.reply_text:
            print(envelope["reply_text"])
            return 0 if envelope["ok"] else int(envelope["returncode"] or 1)
        print(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
        return 0 if envelope["ok"] else int(envelope["returncode"] or 1)
    except RouterError as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except subprocess.TimeoutExpired as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Nutmeg command timed out after {exc.timeout} seconds.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 124


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenClaw-safe router for Nutmeg CLI commands.",
    )
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument(
        "--reply-text",
        action="store_true",
        help="Print the same deterministic reply text that Telegram should send.",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    subparsers = parser.add_subparsers(dest="action")

    _add_simple_json_action(subparsers, "doctor")
    _add_simple_json_action(subparsers, "status")
    _add_simple_json_action(subparsers, "telegram-status")

    seed = subparsers.add_parser("seed-demo")
    _add_league(seed)

    fixtures = subparsers.add_parser("fixtures")
    _add_league(fixtures)
    _add_days(fixtures, default=7)
    fixtures.add_argument("--demo", action="store_true")

    sync = subparsers.add_parser("sync")
    _add_league(sync)
    _add_days(sync, default=14)
    sync.add_argument("--past-days", type=int, default=0)
    sync.add_argument("--confirm-live", action="store_true")

    refresh = subparsers.add_parser("reference-refresh")
    _add_league(refresh)
    refresh.add_argument("--season", type=int, required=True)
    refresh.add_argument("--confirm-write", action="store_true")

    popular = subparsers.add_parser("popular")
    _add_league(popular)
    _add_days(popular, default=3)
    _add_limit(popular, default=5)
    popular.add_argument("--demo", action="store_true")
    popular.add_argument("--query")

    today = subparsers.add_parser("today")
    _add_league(today)
    _add_days(today, default=3)
    _add_limit(today, default=5)
    today.add_argument("--demo", action="store_true")
    today.add_argument("--briefs", action="store_true")
    today.add_argument("--query")
    today.add_argument("--sort", choices=["kickoff", "popularity"], default="popularity")

    for name in ["snapshot", "odds", "visuals"]:
        item = subparsers.add_parser(name)
        _add_fixture_id(item)
    subparsers.choices["visuals"].add_argument(
        "--output-dir",
        default=".nutmeg-data/visuals",
    )

    for name in ["brief", "analyze"]:
        item = subparsers.add_parser(name)
        _add_fixture_id(item)
        item.add_argument("--query", required=True)

    value = subparsers.add_parser("value")
    _add_league(value)
    _add_days(value, default=3)
    _add_limit(value, default=10)
    value.add_argument("--min-edge", type=float, default=0.03)

    player = subparsers.add_parser("player")
    _add_league(player)
    player.add_argument("--season", type=int, required=True)
    player.add_argument("--team", required=True)
    player.add_argument("--player", required=True)
    player.add_argument("--similar-limit", type=int, default=5)

    daily = subparsers.add_parser("daily")
    _add_league(daily)
    _add_days(daily, default=3)
    _add_limit(daily, default=5)
    daily.add_argument("--query", default="Give me the pre-match operator brief.")
    daily.add_argument("--live-sync", action="store_true")
    daily.add_argument("--briefs", action="store_true")
    daily.add_argument("--dispatch-telegram", action="store_true")
    daily.add_argument("--confirm-live", action="store_true")
    daily.add_argument("--confirm-dispatch", action="store_true")

    zucai = subparsers.add_parser("zucai-report")
    zucai.add_argument("--issue-id", default="26068")
    zucai.add_argument("--issue-file")
    zucai.add_argument("--odds-file")
    zucai.add_argument("--overrides-file")
    zucai.add_argument("--output-dir", default=".nutmeg-data/zucai")
    zucai.add_argument("--pdf", action="store_true")
    zucai.add_argument("--dispatch-telegram", action="store_true")
    zucai.add_argument("--confirm-dispatch", action="store_true")

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--dataset", default="starter")
    _add_simple_json_action(subparsers, "review")

    record = subparsers.add_parser("prediction-record")
    _add_fixture_id(record)
    _add_league(record)
    record.add_argument("--home-team", required=True)
    record.add_argument("--away-team", required=True)
    record.add_argument("--home-probability", type=float, required=True)
    record.add_argument("--draw-probability", type=float, required=True)
    record.add_argument("--away-probability", type=float, required=True)
    record.add_argument("--pick", choices=["home", "draw", "away"], required=True)
    record.add_argument("--notes")
    record.add_argument("--confirm-write", action="store_true")

    outcome = subparsers.add_parser("prediction-outcome")
    outcome.add_argument("--prediction-id", type=int, required=True)
    outcome.add_argument("--actual", choices=["home", "draw", "away"], required=True)
    outcome.add_argument("--confirm-write", action="store_true")

    for name in (
        "operator-sale-ingest",
        "operator-schedule-check",
        "operator-evidence-ingest",
    ):
        operator_manifest = subparsers.add_parser(name)
        operator_manifest.add_argument("--manifest", required=True)
        operator_manifest.add_argument("--contract-version", required=True)

    return parser


def _extract_action(argv: list[str]) -> str | None:
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item == "--timeout":
            skip_next = True
            continue
        if item in {"--print-command", "--reply-text", "-h", "--help"}:
            continue
        if item.startswith("-"):
            continue
        return item
    return None


def _validate_options(options: argparse.Namespace) -> None:
    _validate_timeout(options.timeout)
    for attr in ["league"]:
        if hasattr(options, attr):
            _validate_league(getattr(options, attr))
    if hasattr(options, "fixture_id"):
        _validate_fixture_id(options.fixture_id)
    for attr in ["days", "past_days"]:
        if hasattr(options, attr):
            _validate_int_range(attr, getattr(options, attr), minimum=0, maximum=60)
    if hasattr(options, "limit"):
        _validate_int_range("limit", options.limit, minimum=1, maximum=25)
    if hasattr(options, "season"):
        _validate_int_range("season", options.season, minimum=1990, maximum=2100)
    if hasattr(options, "similar_limit"):
        _validate_int_range("similar-limit", options.similar_limit, minimum=1, maximum=20)
    for attr in ["team", "player", "home_team", "away_team"]:
        if hasattr(options, attr):
            _validate_text(attr, getattr(options, attr), maximum=120)
    for attr in [
        "query",
        "notes",
        "dataset",
        "output_dir",
        "report_file",
        "llm_mode",
        "openclaw_model",
        "issue_id",
        "issue_file",
        "odds_file",
        "overrides_file",
        "provider",
        "date",
        "revision_text",
    ]:
        if hasattr(options, attr) and getattr(options, attr) is not None:
            _validate_text(attr, getattr(options, attr), maximum=500)
    if hasattr(options, "min_edge") and not 0 <= options.min_edge <= 1:
        raise RouterError("min-edge must be between 0 and 1.")
    _validate_probabilities(options)
    if options.action == "sync" and not options.confirm_live:
        raise RouterError("`sync` requires --confirm-live.")
    if options.action == "reference-refresh" and not options.confirm_write:
        raise RouterError("`reference-refresh` requires --confirm-write.")
    if options.action == "daily" and options.live_sync and not options.confirm_live:
        raise RouterError("`daily --live-sync` requires --confirm-live.")
    if options.action == "daily" and options.dispatch_telegram and not options.confirm_dispatch:
        raise RouterError("`daily --dispatch-telegram` requires --confirm-dispatch.")
    if (
        options.action == "zucai-report"
        and options.dispatch_telegram
        and not options.confirm_dispatch
    ):
        raise RouterError("`zucai-report --dispatch-telegram` requires --confirm-dispatch.")
    if options.action in {"prediction-record", "prediction-outcome"} and not options.confirm_write:
        raise RouterError(f"`{options.action}` requires --confirm-write.")
    if options.action in {
        "operator-sale-ingest",
        "operator-schedule-check",
        "operator-evidence-ingest",
    }:
        _validate_operator_manifest(options)


def _validate_operator_manifest(options: argparse.Namespace) -> None:
    expected_version = {
        "operator-sale-ingest": "official-sale-slate-v1",
        "operator-schedule-check": "official-schedule-check-v1",
        "operator-evidence-ingest": "evidence-intake-v1",
    }[options.action]
    if options.contract_version != expected_version:
        raise RouterError(f"contract version must be exactly {expected_version}")
    raw = options.manifest.strip()
    if "://" in raw or raw.startswith(("{", "[")):
        raise RouterError("operator manifest must be a local file reference")
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = DEFAULT_OPERATOR_INTAKE_ROOT / candidate
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(DEFAULT_OPERATOR_INTAKE_ROOT)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        raise RouterError(
            "operator manifest must resolve below the configured intake root"
        ) from error
    if not resolved.is_file():
        raise RouterError("operator manifest must be a regular file")
    options.manifest = str(resolved)


def _validate_probabilities(options: argparse.Namespace) -> None:
    probability_attrs = ["home_probability", "draw_probability", "away_probability"]
    if not all(hasattr(options, attr) for attr in probability_attrs):
        return
    values = [getattr(options, attr) for attr in probability_attrs]
    if any(value < 0 or value > 1 for value in values):
        raise RouterError("Prediction probabilities must be between 0 and 1.")
    if abs(sum(values) - 1) > 0.001:
        raise RouterError("Prediction probabilities must sum to 1.")


def _add_simple_json_action(subparsers, name: str) -> None:
    subparsers.add_parser(name)


def _add_league(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--league", default="epl")


def _add_days(parser: argparse.ArgumentParser, *, default: int) -> None:
    parser.add_argument("--days", type=int, default=default)


def _add_limit(parser: argparse.ArgumentParser, *, default: int) -> None:
    parser.add_argument("--limit", type=int, default=default)


def _add_fixture_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fixture-id", required=True)


def _validate_timeout(value: int) -> None:
    _validate_int_range("timeout", value, minimum=1, maximum=600)


def _validate_league(value: str) -> None:
    if not LEAGUE_RE.fullmatch(value):
        raise RouterError(f"Invalid league `{value}`.")


def _validate_fixture_id(value: str) -> None:
    if not FIXTURE_ID_RE.fullmatch(value):
        raise RouterError(f"Invalid fixture id `{value}`.")


def _validate_int_range(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if value < minimum or value > maximum:
        raise RouterError(f"{name} must be between {minimum} and {maximum}.")


def _validate_text(name: str, value: str, *, maximum: int) -> None:
    if not value.strip():
        raise RouterError(f"{name} cannot be empty.")
    if len(value) > maximum:
        raise RouterError(f"{name} is too long; max {maximum} characters.")
    if any(char in value for char in ["\x00", "\r", "\n"]):
        raise RouterError(f"{name} cannot contain control characters.")


def render_reply_text(
    *,
    action: str,
    ok: bool,
    payload: Any,
    stdout: str,
    stderr: str,
) -> str:
    if not ok:
        error = (stderr or stdout).strip() or "Nutmeg command failed without details."
        return f"`{action}` 执行失败：\n{_truncate(error, 1600)}"
    if not isinstance(payload, dict):
        text = stdout.strip()
        if text:
            return _truncate(text, 3500)
        return f"`{action}` 执行完成，但没有返回结构化 payload。"

    if action == "status":
        return _render_status(payload)
    if action == "popular":
        return _render_popular(payload)
    if action == "zucai-report":
        return _render_zucai(payload)

    return _render_generic_success(action, payload)


def _render_status(payload: dict[str, Any]) -> str:
    agent = payload.get("agent") or {}
    odds = payload.get("odds_provider") or {}
    bot = payload.get("bot_fallback") or {}
    synthesis = payload.get("synthesis") or {}
    odds_state = "已配置" if odds.get("configured") else "未配置"
    odds_health = "有 health 指标" if odds.get("health_metrics_available") else "暂无 health 指标"
    bot_state = "已启用" if bot.get("enabled") else "未启用"
    synthesis_state = "已启用" if synthesis.get("enabled") else "未启用"
    bot_model = f"{bot.get('provider', 'unknown')} / {bot.get('model', 'unknown')}"
    synthesis_model = (
        f"{synthesis.get('provider', 'unknown')} / {synthesis.get('model', 'unknown')}"
    )
    return "\n".join(
        [
            "系统状态：",
            "",
            f"- 执行器：{agent.get('executor', 'unknown')}",
            f"- LangGraph：{'可用' if agent.get('langgraph_available') else '不可用'}",
            f"- 赔率数据源：{odds.get('name', 'unknown')}，{odds_state}",
            f"- 赔率健康检查：{odds_health}",
            f"- Bot fallback：{bot_state}，模型配置为 `{bot_model}`",
            f"- Synthesis：{synthesis_state}，模型配置为 `{synthesis_model}`",
            "",
            "当前可用 Nutmeg 命令示例：",
            "- `/popular epl 3`",
            "- `/today epl 3`",
            "- `/brief <fixture_id> 这场比赛怎么看？`",
            "- `/value epl 3`",
            "- `/zucai 26068`",
        ]
    )


def _render_popular(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    league = payload.get("league", "epl")
    days = payload.get("days", 3)
    if not items:
        reason = payload.get("empty_reason") or "当前没有可展示的热门比赛。"
        return f"`/popular {league} {days}` 暂无结果：{reason}"
    lines = [f"热门比赛（{league}，未来 {days} 天）：", ""]
    for item in items:
        popularity = item.get("popularity") or {}
        fixture_id = item.get("fixture_id")
        home = item.get("home_team")
        away = item.get("away_team")
        kickoff = item.get("kickoff_at")
        score = popularity.get("score", "-")
        tier = popularity.get("tier", "-")
        lines.append(
            f"{item.get('rank', '-')}. {home} vs {away}"
            f"｜fixture_id `{fixture_id}`｜{kickoff}｜热度 {score}/{tier}"
        )
        if fixture_id:
            lines.append(f"   下一步：`/brief {fixture_id} 这场比赛怎么看？`")
    return "\n".join(lines)


def _render_zucai(payload: dict[str, Any]) -> str:
    artifacts = payload.get("artifacts") or {}
    lines = [f"传统足彩报告已生成：issue `{payload.get('issue_id', '-')}`"]
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    recommendations = payload.get("recommendations") or []
    if recommendations:
        lines.append("")
        lines.append("重点建议：")
        for item in recommendations[:5]:
            home = item.get("home_team", "-")
            away = item.get("away_team", "-")
            pick = item.get("pick", "-")
            lines.append(f"- {item.get('match_no', '-')}. {home} vs {away}｜{pick}")
    return "\n".join(lines)


def _render_generic_success(action: str, payload: dict[str, Any]) -> str:
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    summary = payload.get("summary")
    lines = [f"`{action}` 执行完成。"]
    if summary:
        lines.extend(["", _truncate(str(summary), 1200)])
    if artifacts:
        lines.extend(["", "产物："])
        for key, value in artifacts.items():
            lines.append(f"- {key}: `{value}`")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.extend(["", "警告："])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: maximum - 1].rstrip() + "…"


def _parse_json_payload(stdout: str) -> Any | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


@contextlib.contextmanager
def _command_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (NameError, UnboundLocalError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
