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


@pytest.mark.parametrize(
    "action",
    [
        "content",
        "daily-content-pack",
        "video-production-packet",
        "wechat-article-pack",
        "wechat-draft-push",
        "seedance-submit",
        "seedance-poll",
    ],
)
def test_router_rejects_retired_non_betting_actions(action: str) -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="Unsupported action"):
        router.parse_request([action])


def test_router_builds_only_existing_nutmeg_commands() -> None:
    router = _load_router()
    help_result = subprocess.run(
        ["uv", "run", "nutmeg", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    help_text = help_result.stdout
    requests = [
        router.parse_request(["doctor"]),
        router.parse_request(["status"]),
        router.parse_request(["telegram-status"]),
        router.parse_request(["fixtures", "--league", "epl", "--demo"]),
        router.parse_request(["popular", "--league", "epl"]),
        router.parse_request(["today", "--league", "epl"]),
        router.parse_request(["snapshot", "--fixture-id", "epl-001"]),
        router.parse_request(["odds", "--fixture-id", "epl-001"]),
        router.parse_request(["brief", "--fixture-id", "epl-001", "--query", "q"]),
        router.parse_request(["analyze", "--fixture-id", "epl-001", "--query", "q"]),
        router.parse_request(["value", "--league", "epl"]),
        router.parse_request(
            [
                "player",
                "--league",
                "epl",
                "--season",
                "2025",
                "--team",
                "Arsenal",
                "--player",
                "Saka",
            ]
        ),
        router.parse_request(["visuals", "--fixture-id", "epl-001"]),
        router.parse_request(["daily", "--league", "epl"]),
        router.parse_request(["zucai-report", "--issue-id", "26068"]),
        router.parse_request(["jczq-mixed-report", "--provider", "sample"]),
        router.parse_request(["jczq-daily-advisor", "--provider", "sample"]),
        router.parse_request(["eval"]),
        router.parse_request(["review"]),
    ]

    for request in requests:
        command = router.build_command(request)
        assert command[:3] == ["uv", "run", "nutmeg"]
        assert command[3] in help_text


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
    assert "reply_text" in envelope
    assert "epl-001" in envelope["reply_text"]
    assert envelope["stdout"] == ""


def test_router_reply_text_flag_is_global_before_action() -> None:
    router = _load_router()

    request = router.parse_request(["--reply-text", "status"])

    assert request.options.reply_text is True
    assert request.action == "status"


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


def test_router_keeps_jczq_mixed_report_sample_only_after_live_retirement() -> None:
    router = _load_router()

    request = router.parse_request(["jczq-mixed-report"])
    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "jczq-mixed-report",
        "--provider",
        "sample",
        "--output-dir",
        ".nutmeg-data/jczq",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="retired"):
        router.parse_request(["jczq-mixed-report", "--provider", "live"])


def test_router_builds_jczq_daily_advisor_command_and_requires_dispatch_confirmation() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "jczq-daily-advisor",
            "--provider",
            "sample",
            "--date",
            "2026-05-01",
            "--output-dir",
            ".nutmeg-data/jczq",
            "--dispatch-telegram",
            "--confirm-dispatch",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "jczq-daily-advisor",
        "--provider",
        "sample",
        "--date",
        "2026-05-01",
        "--output-dir",
        ".nutmeg-data/jczq",
        "--dispatch-telegram",
        "--no-dry-run",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="--confirm-dispatch"):
        router.parse_request(["jczq-daily-advisor", "--dispatch-telegram"])


def test_router_renders_jczq_daily_advisor_reply_text() -> None:
    router = _load_router()

    text = router.render_reply_text(
        action="jczq-daily-advisor",
        ok=True,
        payload={
            "run_date": "2026-05-02",
            "official_last_update": "2026-05-02 15:08:23",
            "summary": "主线保留，机会票小注。",
            "plans": [
                {
                    "name": "最终主方案",
                    "description": "主线方案",
                    "total_odds": 99.07,
                    "legs": [
                        {
                            "match_no": "周六014",
                            "league": "德甲",
                            "home_team": "法兰克福",
                            "away_team": "汉堡",
                            "play": "让球胜平负",
                            "pick": "让负",
                            "odds": 2.09,
                        }
                    ],
                    "risk_note": "副仓小注。",
                }
            ],
            "artifacts": {"markdown_path": ".nutmeg-data/jczq/daily/report.md"},
            "warnings": [],
        },
        stdout="",
        stderr="",
    )

    assert "竞彩足球每日方案（2026-05-02）" in text
    assert "最终主方案" in text
    assert "周六014" in text
    assert ".nutmeg-data/jczq/daily/report.md" in text
