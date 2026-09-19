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


def test_router_calls_the_same_jczq_status_workflow() -> None:
    router = _load_router()

    request = router.parse_request(["jczq-status", "--day", "2026-09-20"])

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "workflow",
        "jczq-status",
        "--day",
        "2026-09-20",
    ]


def test_router_rejects_unknown_actions() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="Unsupported action"):
        router.parse_request(["shell", "rm", "-rf", "/"])


def test_router_builds_operator_sale_manifest_commands(tmp_path, monkeypatch) -> None:
    router = _load_router()
    intake = tmp_path / "intake"
    intake.mkdir()
    sale = intake / "sale.json"
    check = intake / "check.json"
    sale.write_text("{}", "utf-8")
    check.write_text("{}", "utf-8")
    monkeypatch.setattr(router, "DEFAULT_OPERATOR_INTAKE_ROOT", intake.resolve())

    sale_request = router.parse_request(
        [
            "operator-sale-ingest",
            "--manifest",
            str(sale),
            "--contract-version",
            "official-sale-slate-v1",
        ]
    )
    check_request = router.parse_request(
        [
            "operator-schedule-check",
            "--manifest",
            str(check),
            "--contract-version",
            "official-schedule-check-v1",
        ]
    )

    assert router.build_command(sale_request) == [
        "uv",
        "run",
        "nutmeg",
        "workflow",
        "ingest-official-sale",
        "--manifest",
        str(sale.resolve()),
        "--contract-version",
        "official-sale-slate-v1",
    ]
    assert router.build_command(check_request) == [
        "uv",
        "run",
        "nutmeg",
        "workflow",
        "record-official-schedule-check",
        "--manifest",
        str(check.resolve()),
        "--contract-version",
        "official-schedule-check-v1",
    ]


def test_router_builds_strict_operator_evidence_manifest_command(
    tmp_path, monkeypatch
) -> None:
    router = _load_router()
    intake = tmp_path / "intake"
    intake.mkdir()
    manifest = intake / "evidence.json"
    manifest.write_text("{}", "utf-8")
    monkeypatch.setattr(router, "DEFAULT_OPERATOR_INTAKE_ROOT", intake.resolve())

    request = router.parse_request(
        [
            "operator-evidence-ingest",
            "--manifest",
            str(manifest),
            "--contract-version",
            "evidence-intake-v1",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "workflow",
        "ingest-evidence",
        "--manifest",
        str(manifest.resolve()),
    ]


@pytest.mark.parametrize(
    ("manifest", "contract"),
    [
        ("https://example.test/evidence.json", "evidence-intake-v1"),
        ('{"schema_version":"evidence-intake-v1"}', "evidence-intake-v1"),
        ("../outside.json", "evidence-intake-v1"),
        ("evidence.json", "evidence-intake-v2"),
    ],
)
def test_router_rejects_unsafe_operator_evidence_inputs(
    tmp_path, monkeypatch, manifest, contract
) -> None:
    router = _load_router()
    intake = tmp_path / "intake"
    intake.mkdir()
    (intake / "evidence.json").write_text("{}", "utf-8")
    monkeypatch.setattr(router, "DEFAULT_OPERATOR_INTAKE_ROOT", intake.resolve())

    with pytest.raises(router.RouterError):
        router.parse_request(
            [
                "operator-evidence-ingest",
                "--manifest",
                manifest,
                "--contract-version",
                contract,
            ]
        )


def test_router_rejects_evidence_symlink_escaping_intake_root(
    tmp_path, monkeypatch
) -> None:
    router = _load_router()
    intake = tmp_path / "intake"
    intake.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", "utf-8")
    escaping = intake / "escaping.json"
    escaping.symlink_to(outside)
    monkeypatch.setattr(router, "DEFAULT_OPERATOR_INTAKE_ROOT", intake.resolve())

    with pytest.raises(router.RouterError, match="below the configured intake root"):
        router.parse_request(
            [
                "operator-evidence-ingest",
                "--manifest",
                str(escaping),
                "--contract-version",
                "evidence-intake-v1",
            ]
        )


@pytest.mark.parametrize(
    ("manifest", "contract"),
    (
        ("https://example.test/sale.json", "official-sale-slate-v1"),
        ('{"schema_version":"official-sale-slate-v1"}', "official-sale-slate-v1"),
        ("../outside.json", "official-sale-slate-v1"),
        ("sale.json", "official-sale-slate-v2"),
        ("~nutmeg-user-that-does-not-exist/sale.json", "official-sale-slate-v1"),
    ),
)
def test_router_rejects_unsafe_operator_sale_inputs(
    tmp_path, monkeypatch, manifest, contract
) -> None:
    router = _load_router()
    intake = tmp_path / "intake"
    intake.mkdir()
    (intake / "sale.json").write_text("{}", "utf-8")
    monkeypatch.setattr(router, "DEFAULT_OPERATOR_INTAKE_ROOT", intake.resolve())

    with pytest.raises(router.RouterError):
        router.parse_request(
            [
                "operator-sale-ingest",
                "--manifest",
                manifest,
                "--contract-version",
                contract,
            ]
        )


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
