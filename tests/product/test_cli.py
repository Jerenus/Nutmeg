import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import product as product_cli
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.wiring import build_product_services


def test_product_services_refuse_uninitialized_kernel(tmp_path: Path) -> None:
    with pytest.raises(ProductNotReadyError, match="ontology is not initialized"):
        build_product_services(AppSettings(data_dir=tmp_path / "data"))


def test_product_services_compose_only_current_kernel(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    build_ontology_kernel(settings).initialize()

    services = build_product_services(settings)

    assert services.kernel.status().integrity_check == "ok"
    assert services.queries.health().ontology_schema_version == MIGRATIONS[-1].version
    assert services.settings is settings


def test_app_command_binds_loopback_by_default(monkeypatch, tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    build_ontology_kernel(settings).initialize()
    captured: dict[str, object] = {}
    monkeypatch.setattr(product_cli._cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda application, host, port: captured.update(
            {"app": application, "host": host, "port": port}
        ),
    )

    result = CliRunner().invoke(app, ["app"])

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8788


def _invoke_scoreboard(*args: str):
    return CliRunner().invoke(app, ["scoreboard", *args])


def _json_result(result) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert result.stdout.strip() == canonical_json(payload)
    return payload


def test_scoreboard_cli_drives_explicit_isolated_authority_lifecycle(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "isolated-data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    at = "2026-08-24T10:00:00+00:00"

    status = _json_result(
        _invoke_scoreboard("status", "--data-dir", str(data_dir))
    )
    assert status["authority"]["state"] == "legacy"
    assert status["targets"]["data_dir"] == str(data_dir)

    missing_ack = _invoke_scoreboard(
        "observe",
        "--data-dir",
        str(data_dir),
        "--group-key",
        "chains",
        "--metric-key",
        "main",
        "--tally",
        "1/1",
        "--detail",
        "formal manual observation",
        "--status",
        "active",
        "--evidence-type",
        "adjudication",
        "--evidence-id",
        "adj-source",
        "--effective-at",
        at,
        "--requested-at",
        at,
    )
    assert missing_ack.exit_code != 0

    observed = _json_result(
        _invoke_scoreboard(
            "observe",
            "--data-dir",
            str(data_dir),
            "--group-key",
            "chains",
            "--metric-key",
            "main",
            "--tally",
            "1/1",
            "--detail",
            "formal manual observation",
            "--status",
            "active",
            "--numerator",
            "1",
            "--denominator",
            "1",
            "--value",
            "1",
            "--unit",
            "ratio",
            "--evidence-type",
            "adjudication",
            "--evidence-id",
            "adj-source",
            "--effective-at",
            at,
            "--requested-at",
            at,
            "--acknowledge-manual-source",
        )
    )
    assert observed["status"] == "committed"

    build = kernel.calibrate.build(
        CalibrateRequest(as_of=at, built_at="2026-08-24T10:05:00+00:00")
    )
    legacy = tmp_path / "legacy-scoreboard.json"
    legacy.write_text(
        '{"updated_at":"2026-08-24T09:00:00Z","chains":{"main":1}}\n',
        encoding="utf-8",
    )
    classification = tmp_path / "classification.json"
    classification.write_text(
        canonical_json(
            [
                {
                    "group_key": "chains",
                    "metric_key": "main",
                    "classification": "formal_manual",
                    "target_ref": "scoreboard_observation:chains:main",
                }
            ]
        ),
        encoding="utf-8",
    )
    shadow = _json_result(
        _invoke_scoreboard(
            "shadow",
            "--data-dir",
            str(data_dir),
            "--legacy-file",
            str(legacy),
            "--classification-file",
            str(classification),
            "--projection-version",
            "sb-v1",
            "--source-high-watermark",
            str(build.high_watermark),
            "--requested-at",
            at,
            "--acknowledge-manual-source",
        )
    )
    review_id = shadow["result_refs"][0]["object_id"]

    sop_root = tmp_path / "sop"
    shutil.copytree(Path("tests/fixtures/m5/sop"), sop_root)
    cutover_args = [
        "cutover",
        "--data-dir",
        str(data_dir),
        "--legacy-file",
        str(legacy),
        "--review-id",
        review_id,
        "--expected-authority-version",
        "1",
        "--projection-version",
        "sb-v1",
        "--source-high-watermark",
        str(build.high_watermark),
        "--requested-at",
        at,
    ]
    for name in (
        "CONSTITUTION.md",
        "RUNBOOK.md",
        "RULEBOOK.md",
        "AGENTS.md",
        "CLAUDE.md",
    ):
        cutover_args.extend(["--sop-file", str(sop_root / name)])
    blocked = _invoke_scoreboard(*cutover_args)
    assert blocked.exit_code != 0
    cutover = _json_result(_invoke_scoreboard(*cutover_args, "--approve"))
    assert cutover["status"] == "committed"

    destination = tmp_path / "compatibility" / "scoreboard.json"
    exported = _json_result(
        _invoke_scoreboard(
            "export",
            "--data-dir",
            str(data_dir),
            "--destination",
            str(destination),
            "--expected-authority-version",
            "2",
            "--requested-at",
            at,
        )
    )
    verified = _json_result(
        _invoke_scoreboard(
            "verify-export",
            "--data-dir",
            str(data_dir),
            "--destination",
            str(destination),
        )
    )
    assert verified["status"] == "verified"
    assert verified["sha256"] == exported["sha256"]

    missing_data_dir = _invoke_scoreboard("observe", "--approve")
    assert missing_data_dir.exit_code == 2
