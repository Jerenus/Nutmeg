import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import product as product_cli
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product import wiring as product_wiring
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeError,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
    SourceIdentity,
)
from nutmeg.product.operator_workers import audit_current_candidate
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
    assert (
        services.kernel.protected_tickets._operator_candidate_auditor
        is audit_current_candidate
    )


def test_app_command_binds_loopback_by_default(monkeypatch, tmp_path: Path) -> None:
    data_dir = (tmp_path / "data").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=data_dir,
    )
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


def test_app_command_validates_and_locks_before_building_services(
    monkeypatch, tmp_path: Path
) -> None:
    from nutmeg.interfaces import product_api
    from nutmeg.product import operator_runtime

    production = (tmp_path / "production").resolve()
    isolated = (tmp_path / "isolated").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=production,
        production_data_dir=production,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key="isolated-operator-signing-key-32-bytes",
    )
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=isolated,
        production_data_dir=production,
        running_commit="a" * 40,
    )
    events: list[object] = []

    monkeypatch.setattr(product_cli._cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        operator_runtime,
        "probe_source_identity",
        lambda: events.append("probe")
        or SourceIdentity(running_commit="a" * 40, dirty=True, resolved=True),
    )

    def validate(candidate_settings, **kwargs):
        events.append(("validate", candidate_settings.data_dir, kwargs))
        return runtime

    monkeypatch.setattr(operator_runtime, "validate_operator_runtime", validate)

    class AppLease:
        def __init__(self, data_dir, *, host, port):
            events.append(("app_lease_init", data_dir, host, port))

        def acquire(self):
            events.append("app_acquire")
            return self

        def release(self):
            events.append("app_release")

    class WriterLease:
        @classmethod
        def shared(cls, data_dir):
            events.append(("writer_lease_init", data_dir))
            return cls()

        def acquire(self):
            events.append("writer_acquire")
            return self

        def release(self):
            events.append("writer_release")

    monkeypatch.setattr(operator_runtime, "ApplicationInstanceLease", AppLease)
    monkeypatch.setattr(operator_runtime, "OntologyWriterLease", WriterLease)

    def build(candidate_settings, *, runtime_config):
        events.append(("build", candidate_settings.data_dir, runtime_config))
        return SimpleNamespace()

    monkeypatch.setattr(product_wiring, "build_product_services", build)
    monkeypatch.setattr(
        product_api,
        "create_product_app",
        lambda services, *, runtime_config: events.append(
            ("create_app", services, runtime_config)
        )
        or "application",
    )
    monkeypatch.setattr(
        "uvicorn.run",
        lambda application, host, port: events.append(
            ("uvicorn", application, host, port)
        ),
    )

    result = CliRunner().invoke(app, ["app", "--data-dir", str(isolated)])

    assert result.exit_code == 0, result.output
    assert events[0] == "probe"
    assert events[1] == (
        "validate",
        isolated,
        {
            "running_commit": "a" * 40,
            "dirty": True,
            "data_dir_was_explicit": True,
        },
    )
    assert [event if isinstance(event, str) else event[0] for event in events] == [
        "probe",
        "validate",
        "app_lease_init",
        "app_acquire",
        "writer_lease_init",
        "writer_acquire",
        "build",
        "create_app",
        "uvicorn",
        "writer_release",
        "app_release",
    ]


def test_app_command_reports_lease_conflict_before_service_construction(
    monkeypatch, tmp_path: Path
) -> None:
    from nutmeg.product import operator_runtime

    production = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=production,
        production_data_dir=production,
    )
    monkeypatch.setattr(product_cli._cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        operator_runtime,
        "probe_source_identity",
        lambda: SourceIdentity(running_commit="a" * 40, dirty=False, resolved=True),
    )

    class ConflictingLease:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self):
            raise OperatorRuntimeError("app_instance_conflict", "already running")

    monkeypatch.setattr(operator_runtime, "ApplicationInstanceLease", ConflictingLease)
    constructed = False

    def build(*_args, **_kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("services must not be constructed")

    monkeypatch.setattr(product_wiring, "build_product_services", build)

    result = CliRunner().invoke(app, ["app"])

    assert result.exit_code != 0
    assert "app_instance_conflict" in result.output
    assert constructed is False


def test_isolated_wiring_rejects_real_token_before_constructing_telegram(
    monkeypatch, tmp_path: Path
) -> None:
    production = (tmp_path / "production").resolve()
    isolated = (tmp_path / "isolated").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=isolated,
        production_data_dir=production,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key="isolated-operator-signing-key-32-bytes",
        telegram_bot_token="real-token-must-not-be-used",
        telegram_allowed_chat_ids="7",
    )
    build_ontology_kernel(settings).initialize()
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=isolated,
        production_data_dir=production,
        running_commit="a" * 40,
    )

    class TelegramMustNotConstruct:
        def __init__(self, **_kwargs):
            raise AssertionError("real Telegram was constructed")

    monkeypatch.setattr(product_wiring, "TelegramBotClient", TelegramMustNotConstruct)

    with pytest.raises(ValueError, match="side effects"):
        build_product_services(settings, runtime_config=runtime)


def test_token_free_isolated_wiring_uses_only_simulated_confirmation(
    tmp_path: Path,
) -> None:
    production = (tmp_path / "production").resolve()
    isolated = (tmp_path / "isolated").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=isolated,
        production_data_dir=production,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key="isolated-operator-signing-key-32-bytes",
        telegram_bot_token=None,
        telegram_allowed_chat_ids=None,
    )
    build_ontology_kernel(settings).initialize()
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=isolated,
        production_data_dir=production,
        running_commit="a" * 40,
    )

    services = build_product_services(settings, runtime_config=runtime)

    assert services.runtime is runtime
    assert services.confirmation_transport_kind == "simulated"
    assert services.operator_actions.telegram is not None


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
    assert observed["targets"]["data_dir"] == str(data_dir.resolve())

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
    assert shadow["targets"] == {
        "classification_file": str(classification.resolve()),
        "data_dir": str(data_dir.resolve()),
        "legacy_file": str(legacy.resolve()),
    }

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
    assert cutover["targets"]["legacy_file"] == str(legacy.resolve())
    assert cutover["targets"]["sop_files"] == [
        str((sop_root / name).resolve())
        for name in (
            "CONSTITUTION.md",
            "RUNBOOK.md",
            "RULEBOOK.md",
            "AGENTS.md",
            "CLAUDE.md",
        )
    ]

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
    assert exported["targets"]["destination"] == str(destination.resolve())
    assert verified["targets"]["destination"] == str(destination.resolve())

    missing_data_dir = _invoke_scoreboard("observe", "--approve")
    assert missing_data_dir.exit_code == 2
