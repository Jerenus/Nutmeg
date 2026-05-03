#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH = ROOT / ".nutmeg-data" / "state" / "openclaw-router.lock"
DEFAULT_TIMEOUT_SECONDS = 180
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
    "jczq-mixed-report",
    "jczq-daily-advisor",
    "daily-content-pack",
    "video-production-packet",
    "wechat-article-pack",
    "wechat-draft-push",
    "seedance-submit",
    "seedance-poll",
    "content",
    "eval",
    "review",
    "prediction-record",
    "prediction-outcome",
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
    if action == "jczq-mixed-report":
        command = [
            *base,
            "jczq-mixed-report",
            "--provider",
            options.provider,
            "--output-dir",
            options.output_dir,
        ]
        if options.pdf:
            command.append("--pdf")
        if options.dispatch_telegram:
            command.extend(["--dispatch-telegram", "--no-dry-run"])
        command.extend(["--format", "json"])
        return command
    if action == "jczq-daily-advisor":
        command = [
            *base,
            "jczq-daily-advisor",
            "--provider",
            options.provider,
            "--date",
            options.date,
            "--output-dir",
            options.output_dir,
        ]
        if options.revision_text:
            command.extend(["--revision-text", options.revision_text])
        if options.dispatch_telegram:
            command.extend(["--dispatch-telegram", "--no-dry-run"])
        command.extend(["--format", "json"])
        return command
    if action == "daily-content-pack":
        command = [
            *base,
            "daily-content-pack",
            "--date",
            options.date,
            "--provider",
            options.provider,
            "--output-dir",
            options.output_dir,
        ]
        if options.pdf:
            command.append("--pdf")
        command.extend(["--format", "json"])
        return command
    if action == "video-production-packet":
        return [
            *base,
            "video-production-packet",
            "--date",
            options.date,
            "--provider",
            options.provider,
            "--output-dir",
            options.output_dir,
            "--format",
            "json",
        ]
    if action == "seedance-submit":
        command = [
            *base,
            "seedance-submit",
        ]
        if options.manifest:
            command.extend(["--manifest", options.manifest])
        if options.run_dir:
            command.extend(["--run-dir", options.run_dir])
        if options.match_id:
            command.extend(["--match-id", options.match_id])
        if options.task_key:
            command.extend(["--task-key", options.task_key])
        command.extend(["--ratio-key", options.ratio_key])
        command.extend(["--max-concurrency", str(options.max_concurrency)])
        if options.confirm_submit:
            command.append("--confirm")
        command.extend(["--format", "json"])
        return command
    if action == "seedance-poll":
        command = [
            *base,
            "seedance-poll",
        ]
        if options.manifest:
            command.extend(["--manifest", options.manifest])
        if options.run_dir:
            command.extend(["--run-dir", options.run_dir])
        if options.download:
            command.append("--download")
        if options.concat:
            command.append("--concat")
        command.extend(["--ratio-key", options.ratio_key])
        if options.output_dir:
            command.extend(["--output-dir", options.output_dir])
        command.extend(["--format", "json"])
        return command
    if action == "content":
        return [
            *base,
            "content-pack",
            "--report-file",
            options.report_file,
            "--limit",
            str(options.limit),
            "--output-dir",
            options.output_dir,
            "--llm-mode",
            options.llm_mode,
            "--openclaw-model",
            options.openclaw_model,
            "--format",
            "json",
        ]
    if action == "wechat-article-pack":
        command = [
            *base,
            "wechat-article-pack",
            "--report-file",
            options.report_file,
            "--output-dir",
            options.output_dir,
            "--thumb-media-id",
            options.thumb_media_id,
        ]
        if options.author:
            command.extend(["--author", options.author])
        if options.source_url:
            command.extend(["--source-url", options.source_url])
        command.extend(["--format", "json"])
        return command
    if action == "wechat-draft-push":
        command = [
            *base,
            "wechat-draft-push",
            "--pack-dir",
            options.pack_dir,
            "--app-id",
            options.app_id,
            "--app-secret",
            options.app_secret,
        ]
        command.append("--dry-run" if options.dry_run else "--no-dry-run")
        if options.confirm_draft:
            command.append("--confirm")
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
    return {
        "ok": completed.returncode == 0,
        "action": request.action,
        "command": command,
        "returncode": completed.returncode,
        "payload": payload,
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

    jczq = subparsers.add_parser("jczq-mixed-report")
    jczq.add_argument("--provider", choices=["live", "sample"], default="live")
    jczq.add_argument("--output-dir", default=".nutmeg-data/jczq")
    jczq.add_argument("--pdf", action="store_true")
    jczq.add_argument("--dispatch-telegram", action="store_true")
    jczq.add_argument("--confirm-dispatch", action="store_true")

    jczq_daily = subparsers.add_parser("jczq-daily-advisor")
    jczq_daily.add_argument("--provider", choices=["live", "sample"], default="live")
    jczq_daily.add_argument("--date", default="today")
    jczq_daily.add_argument("--output-dir", default=".nutmeg-data/jczq")
    jczq_daily.add_argument("--revision-text")
    jczq_daily.add_argument("--dispatch-telegram", action="store_true")
    jczq_daily.add_argument("--confirm-dispatch", action="store_true")

    daily_content = subparsers.add_parser("daily-content-pack")
    daily_content.add_argument("--date", default="today")
    daily_content.add_argument("--provider", choices=["live", "sample"], default="live")
    daily_content.add_argument("--output-dir", default=".nutmeg-data/daily-content")
    daily_content.add_argument("--pdf", action="store_true")

    video_packet = subparsers.add_parser("video-production-packet")
    video_packet.add_argument("--date", default="today")
    video_packet.add_argument("--provider", choices=["live", "sample"], default="live")
    video_packet.add_argument("--output-dir", default=".nutmeg-data/daily-content")

    seedance_submit = subparsers.add_parser("seedance-submit")
    seedance_submit.add_argument("--manifest")
    seedance_submit.add_argument("--run-dir")
    seedance_submit.add_argument("--match-id")
    seedance_submit.add_argument("--task-key")
    seedance_submit.add_argument(
        "--ratio-key", choices=["vertical", "horizontal", "all"], default="vertical"
    )
    seedance_submit.add_argument("--max-concurrency", type=int, default=2)
    seedance_submit.add_argument("--confirm-submit", action="store_true")

    seedance_poll = subparsers.add_parser("seedance-poll")
    seedance_poll.add_argument("--manifest")
    seedance_poll.add_argument("--run-dir")
    seedance_poll.add_argument("--download", action="store_true")
    seedance_poll.add_argument("--concat", action="store_true")
    seedance_poll.add_argument(
        "--ratio-key", choices=["vertical", "horizontal", "all"], default="vertical"
    )
    seedance_poll.add_argument("--output-dir")

    content = subparsers.add_parser("content")
    content.add_argument("--report-file", required=True)
    content.add_argument("--limit", type=int, default=3)
    content.add_argument("--output-dir", default=".nutmeg-data/content")
    content.add_argument("--llm-mode", choices=["openclaw", "deterministic"], default="openclaw")
    content.add_argument("--openclaw-model", default="nyu-openai-chat/gpt-5.5")

    wechat_article = subparsers.add_parser("wechat-article-pack")
    wechat_article.add_argument("--report-file", required=True)
    wechat_article.add_argument("--output-dir", default=".nutmeg-data/wechat")
    wechat_article.add_argument("--thumb-media-id", default="DRY_RUN_COVER_MEDIA_ID")
    wechat_article.add_argument("--author")
    wechat_article.add_argument("--source-url")

    wechat_draft = subparsers.add_parser("wechat-draft-push")
    wechat_draft.add_argument("--pack-dir", required=True)
    wechat_draft.add_argument("--app-id", required=True)
    wechat_draft.add_argument("--app-secret", required=True)
    wechat_draft.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    wechat_draft.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    wechat_draft.add_argument("--confirm-draft", action="store_true")

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
        if item in {"--print-command", "-h", "--help"}:
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
        "manifest",
        "run_dir",
        "match_id",
        "task_key",
        "ratio_key",
        "thumb_media_id",
        "author",
        "source_url",
        "pack_dir",
        "app_id",
        "app_secret",
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
    if (
        options.action == "jczq-mixed-report"
        and options.dispatch_telegram
        and not options.confirm_dispatch
    ):
        raise RouterError("`jczq-mixed-report --dispatch-telegram` requires --confirm-dispatch.")
    if (
        options.action == "jczq-daily-advisor"
        and options.dispatch_telegram
        and not options.confirm_dispatch
    ):
        raise RouterError("`jczq-daily-advisor --dispatch-telegram` requires --confirm-dispatch.")
    if options.action == "wechat-draft-push" and not options.dry_run and not options.confirm_draft:
        raise RouterError("`wechat-draft-push --no-dry-run` requires --confirm-draft.")
    if options.action == "seedance-submit" and not options.confirm_submit:
        raise RouterError("`seedance-submit` requires --confirm-submit.")
    if options.action in {"seedance-submit", "seedance-poll"}:
        if not options.manifest and not options.run_dir:
            raise RouterError(f"`{options.action}` requires --manifest or --run-dir.")
    if hasattr(options, "max_concurrency"):
        _validate_int_range("max-concurrency", options.max_concurrency, minimum=1, maximum=10)
    if options.action in {"prediction-record", "prediction-outcome"} and not options.confirm_write:
        raise RouterError(f"`{options.action}` requires --confirm-write.")


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
