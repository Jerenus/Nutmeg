from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "openclaw" / "nutmeg_command_router.py"


def _load_router():
    spec = importlib.util.spec_from_file_location("nutmeg_command_router", ROUTER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_router_builds_popular_matches_command() -> None:
    router = _load_router()

    request = router.parse_request(["popular", "--league", "epl", "--days", "3"])

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "popular-matches",
        "--league",
        "epl",
        "--days",
        "3",
        "--limit",
        "5",
        "--format",
        "json",
    ]


def test_router_rejects_unknown_actions() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="Unsupported action"):
        router.parse_request(["shell", "rm", "-rf", "/"])


def test_router_requires_confirmation_for_live_sync() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="--confirm-live"):
        router.parse_request(["sync", "--league", "epl", "--days", "14"])


def test_router_requires_confirmation_for_real_telegram_dispatch() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="--confirm-dispatch"):
        router.parse_request(["daily", "--league", "epl", "--dispatch-telegram"])


def test_router_preserves_player_profile_names() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "player",
            "--league",
            "epl",
            "--season",
            "2025",
            "--team",
            "Tottenham Hotspur",
            "--player",
            "Son Heung-min",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "player-profile",
        "--league",
        "epl",
        "--season",
        "2025",
        "--team",
        "Tottenham Hotspur",
        "--player",
        "Son Heung-min",
        "--similar-limit",
        "5",
        "--format",
        "json",
    ]


def test_router_execute_returns_json_envelope(monkeypatch, tmp_path) -> None:
    router = _load_router()

    def fake_run(command, **kwargs):
        assert command[:3] == ["uv", "run", "nutmeg"]
        assert kwargs["cwd"] == ROOT
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"items": [{"fixture_id": "epl-001"}]}),
            stderr="",
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    request = router.parse_request(["popular", "--league", "epl", "--days", "3"])

    envelope = router.execute_request(request, lock_path=tmp_path / "router.lock")

    assert envelope["ok"] is True
    assert envelope["action"] == "popular"
    assert envelope["payload"]["items"][0]["fixture_id"] == "epl-001"
    assert envelope["stdout"] == ""


def test_router_builds_zucai_report_command_and_requires_dispatch_confirmation() -> None:
    router = _load_router()

    request = router.parse_request(["zucai-report", "--issue-id", "26068", "--pdf"])
    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "zucai-report",
        "--issue-id",
        "26068",
        "--output-dir",
        ".nutmeg-data/zucai",
        "--pdf",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="--confirm-dispatch"):
        router.parse_request(["zucai-report", "--issue-id", "26068", "--dispatch-telegram"])


def test_router_builds_content_pack_command() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "content",
            "--report-file",
            ".nutmeg-data/zucai/zucai-26068-report.json",
            "--limit",
            "2",
            "--output-dir",
            ".nutmeg-data/content",
            "--llm-mode",
            "deterministic",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "content-pack",
        "--report-file",
        ".nutmeg-data/zucai/zucai-26068-report.json",
        "--limit",
        "2",
        "--output-dir",
        ".nutmeg-data/content",
        "--llm-mode",
        "deterministic",
        "--openclaw-model",
        "nyu-openai-chat/gpt-5.5",
        "--format",
        "json",
    ]


def test_router_builds_jczq_mixed_report_command_and_requires_dispatch_confirmation() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "jczq-mixed-report",
            "--provider",
            "sample",
            "--output-dir",
            ".nutmeg-data/jczq",
            "--pdf",
        ]
    )
    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "jczq-mixed-report",
        "--provider",
        "sample",
        "--output-dir",
        ".nutmeg-data/jczq",
        "--pdf",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="--confirm-dispatch"):
        router.parse_request(["jczq-mixed-report", "--dispatch-telegram"])


def test_router_builds_daily_content_pack_command() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "daily-content-pack",
            "--date",
            "2026-04-26",
            "--provider",
            "sample",
            "--output-dir",
            ".nutmeg-data/daily-content",
            "--pdf",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "daily-content-pack",
        "--date",
        "2026-04-26",
        "--provider",
        "sample",
        "--output-dir",
        ".nutmeg-data/daily-content",
        "--pdf",
        "--format",
        "json",
    ]


def test_router_requires_confirmation_for_seedance_submit() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="--confirm-submit"):
        router.parse_request(
            ["seedance-submit", "--manifest", ".nutmeg-data/run/seedance-manifest.json"]
        )


def test_router_builds_seedance_poll_run_dir_command() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "seedance-poll",
            "--run-dir",
            ".nutmeg-data/daily-content/20260426/run-120000",
            "--download",
            "--concat",
            "--ratio-key",
            "vertical",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "seedance-poll",
        "--run-dir",
        ".nutmeg-data/daily-content/20260426/run-120000",
        "--download",
        "--concat",
        "--ratio-key",
        "vertical",
        "--format",
        "json",
    ]


def test_router_builds_wechat_article_pack_command() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "wechat-article-pack",
            "--report-file",
            ".nutmeg-data/jczq/report.json",
            "--output-dir",
            ".nutmeg-data/wechat/2026-04-28",
            "--thumb-media-id",
            "cover-media",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "wechat-article-pack",
        "--report-file",
        ".nutmeg-data/jczq/report.json",
        "--output-dir",
        ".nutmeg-data/wechat/2026-04-28",
        "--thumb-media-id",
        "cover-media",
        "--format",
        "json",
    ]


def test_router_builds_wechat_draft_push_command_and_requires_confirmation() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "wechat-draft-push",
            "--pack-dir",
            ".nutmeg-data/wechat/2026-04-28",
            "--app-id",
            "app-id",
            "--app-secret",
            "secret",
            "--dry-run",
        ]
    )
    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "wechat-draft-push",
        "--pack-dir",
        ".nutmeg-data/wechat/2026-04-28",
        "--app-id",
        "app-id",
        "--app-secret",
        "secret",
        "--dry-run",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="--confirm-draft"):
        router.parse_request(
            [
                "wechat-draft-push",
                "--pack-dir",
                ".nutmeg-data/wechat/2026-04-28",
                "--app-id",
                "app-id",
                "--app-secret",
                "secret",
                "--no-dry-run",
            ]
        )
