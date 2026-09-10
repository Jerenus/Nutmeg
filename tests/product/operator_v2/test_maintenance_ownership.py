from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_contracts import OperatorStage
from nutmeg.product.operator_maintenance import OperatorMaintenanceProbe
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.services.telegram_ticket_confirmation import TelegramOwnerHeartbeatService

AT = datetime(2026, 9, 5, 8, tzinfo=UTC)
OPENCLAW_CRON_ARGV = ["openclaw", "cron", "list", "--all", "--json"]
OPENCLAW_TELEGRAM_ARGV = [
    "openclaw",
    "channels",
    "status",
    "--channel",
    "telegram",
    "--json",
]
LAUNCHD_LABELS = (
    "com.nutmeg.decision.am",
    "com.nutmeg.decision.close",
    "com.nutmeg.decision.settle",
    "com.nutmeg.zucai.prep",
    "com.nutmeg.zucai.prep-revision",
    "com.nutmeg.zucai.afternoon",
    "com.nutmeg.zucai.revision",
)


class _Runner:
    def __init__(self, responses: list[SimpleNamespace | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append((list(argv), kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _Heartbeat:
    def __init__(self, status: SimpleNamespace) -> None:
        self._status = status
        self.calls: list[datetime] = []

    def status(self, *, as_of: datetime) -> SimpleNamespace:
        self.calls.append(as_of)
        return self._status


def _completed(
    stdout: bytes | str,
    *,
    returncode: int = 0,
    stderr: bytes = b"",
) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _cron(jobs: list[dict[str, object]]) -> SimpleNamespace:
    return _completed(json.dumps({"jobs": jobs}).encode())


def _telegram(*, accounts: list[dict[str, object]] | None = None) -> SimpleNamespace:
    return _completed(
        json.dumps(
            {
                "channelAccounts": {
                    "telegram": accounts
                    if accounts is not None
                    else [
                        {
                            "accountId": "nutmeg",
                            "configured": True,
                            "running": True,
                            "connected": True,
                            "lastConnectedAt": 1_788_545_715_853,
                            "lastStartAt": 1_788_537_894_212,
                            "lastTransportActivityAt": 1_788_545_715_853,
                            "tokenSource": "secret-value",
                            "tokenStatus": "configured",
                            "lastError": "sensitive diagnostic",
                            "chatId": "123456",
                        }
                    ],
                }
            }
        ).encode()
    )


def _launchd(label: str, *, exit_code: int = 0) -> SimpleNamespace:
    return _completed(
        (
            f"gui/{os.getuid()}/{label} = {{\n"
            "\tstate = not running\n"
            "\truns = 11\n"
            f"\tlast exit code = {exit_code}\n"
            "}\n"
        ).encode()
    )


def _heartbeat(*, available: bool = True, blocking_code: str | None = None) -> _Heartbeat:
    return _Heartbeat(
        SimpleNamespace(
            configured=True,
            available=available,
            blocking_code=blocking_code,
            owner_instance_id="openclaw-primary",
            last_heartbeat_at="2026-09-05T07:59:30+00:00",
            lease_expires_at="2026-09-05T08:01:00+00:00",
        )
    )


def _responses(jobs: list[dict[str, object]]) -> list[SimpleNamespace]:
    return [_cron(jobs), _telegram(), *[_launchd(label) for label in LAUNCHD_LABELS]]


def _job(
    name: str,
    *,
    enabled: bool = True,
    argv: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"kind": "systemEvent"}
    if argv is not None:
        payload["argv"] = argv
    return {
        "name": name,
        "enabled": enabled,
        "payload": payload,
        "lastRunAtMs": 1_788_480_000_029,
        "lastRunStatus": "ok",
    }


@pytest.mark.parametrize(
    ("name", "argv", "stage"),
    [
        ("Nutmeg-AM数据入库", None, OperatorStage.JCZQ_AM),
        ("Nutmeg-临场数据刷新", None, OperatorStage.JCZQ_AM),
        ("Nutmeg-每日最终决策", None, OperatorStage.JCZQ_DECISION),
        ("Nutmeg-最终决策受限补跑", None, OperatorStage.JCZQ_DECISION_RECOVERY),
        ("Nutmeg-收盘前闸门", None, OperatorStage.JCZQ_PRECLOSE_CHECK),
        ("Nutmeg-收盘", None, OperatorStage.JCZQ_CLOSE),
        ("Nutmeg-收盘交付确认", None, OperatorStage.JCZQ_CLOSE_VERIFY),
        ("Nutmeg-昨日结算", None, OperatorStage.JCZQ_SETTLE),
        ("Nutmeg-D1D2补结算", None, OperatorStage.JCZQ_SETTLEMENT_RETRY),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "run-strict",
                "--stage",
                "am",
            ],
            OperatorStage.JCZQ_AM,
        ),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "run-strict",
                "--stage",
                "close",
            ],
            OperatorStage.JCZQ_CLOSE,
        ),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "run-strict",
                "--stage",
                "settle",
            ],
            OperatorStage.JCZQ_SETTLE,
        ),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "validate-preclose",
            ],
            OperatorStage.JCZQ_PRECLOSE_CHECK,
        ),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "verify-close",
            ],
            OperatorStage.JCZQ_CLOSE_VERIFY,
        ),
        (
            "Unrelated job",
            ["uv", "run", "nutmeg", "decision-settle", "--format", "json"],
            OperatorStage.JCZQ_SETTLE,
        ),
        (
            "Unrelated job",
            [
                "uv",
                "run",
                "python",
                "scripts/openclaw/nutmeg_scheduler_ops.py",
                "retry-settlement",
                "--days",
                "1",
                "2",
            ],
            OperatorStage.JCZQ_SETTLEMENT_RETRY,
        ),
        (
            "Unrelated job",
            [
                "sh",
                "-lc",
                "uv run python scripts/openclaw/nutmeg_scheduler_ops.py "
                "run-strict --stage am --run-date $(date +%Y-%m-%d)",
            ],
            OperatorStage.JCZQ_AM,
        ),
        (
            "Unrelated job",
            [
                "sh",
                "-lc",
                "set -a; source .env; set +a; uv run nutmeg decision-settle "
                "--run-date $(date -v-1d +%Y-%m-%d) --output-dir data "
                "--no-dry-run --format json && uv run python "
                "scripts/openclaw/nutmeg_scheduler_ops.py build-context "
                "--run-date $(date +%Y-%m-%d)",
            ],
            OperatorStage.JCZQ_SETTLE,
        ),
    ],
)
def test_closed_openclaw_registry_maps_exact_names_and_normalized_argv(
    name: str,
    argv: list[str] | None,
    stage: OperatorStage,
) -> None:
    runner = _Runner(_responses([_job(name, argv=argv)]))

    result = OperatorMaintenanceProbe(runner=runner, heartbeat_service=_heartbeat()).read(as_of=AT)

    assert result.diagnostic_state == "available"
    openclaw = [claim for claim in result.claims if claim.owner_kind == "openclaw"]
    assert [(claim.business_label, claim.stage) for claim in openclaw] == [(name, stage)]


@pytest.mark.parametrize(
    ("label", "stage"),
    [
        ("com.nutmeg.decision.am", OperatorStage.JCZQ_AM),
        ("com.nutmeg.decision.close", OperatorStage.JCZQ_CLOSE),
        ("com.nutmeg.decision.settle", OperatorStage.JCZQ_SETTLE),
        ("com.nutmeg.zucai.prep", OperatorStage.ZUCAI_PREP),
        ("com.nutmeg.zucai.prep-revision", OperatorStage.ZUCAI_PREP_REVISION),
        ("com.nutmeg.zucai.afternoon", OperatorStage.ZUCAI_AFTERNOON),
        ("com.nutmeg.zucai.revision", OperatorStage.ZUCAI_REVISION),
    ],
)
def test_closed_launchd_registry_maps_every_label(
    label: str,
    stage: OperatorStage,
) -> None:
    runner = _Runner(_responses([]))

    result = OperatorMaintenanceProbe(runner=runner, heartbeat_service=_heartbeat()).read(as_of=AT)

    claim = next(item for item in result.claims if item.business_label == label)
    assert claim.stage is stage
    assert claim.owner_kind == "launchd"
    assert claim.loaded is True
    assert claim.enabled is None


def test_every_enabled_owner_is_a_claim_and_duplicates_conflict() -> None:
    jobs = [
        _job("Nutmeg-AM数据入库"),
        _job("Nutmeg-临场数据刷新"),
        _job("Nutmeg-收盘前闸门"),
    ]
    runner = _Runner(_responses(jobs))

    result = OperatorMaintenanceProbe(runner=runner, heartbeat_service=_heartbeat()).read(as_of=AT)

    am = next(stage for stage in result.stages if stage.stage is OperatorStage.JCZQ_AM)
    preclose = next(
        stage for stage in result.stages if stage.stage is OperatorStage.JCZQ_PRECLOSE_CHECK
    )
    assert am.claim_count == 3  # two OpenClaw jobs plus the loaded launchd label
    assert am.conflict is True
    assert preclose.claim_count == 1
    assert preclose.conflict is False


def test_disabled_openclaw_job_is_reported_but_does_not_claim_ownership() -> None:
    runner = _Runner(_responses([_job("Nutmeg-AM数据入库", enabled=False)]))

    result = OperatorMaintenanceProbe(runner=runner, heartbeat_service=_heartbeat()).read(as_of=AT)

    row = next(claim for claim in result.claims if claim.owner_kind == "openclaw")
    stage = next(item for item in result.stages if item.stage is OperatorStage.JCZQ_AM)
    assert row.enabled is False
    assert stage.claim_count == 1  # the loaded launchd label only


@pytest.mark.parametrize(
    "jobs",
    [
        [_job("Nutmeg-未知维护")],
        [
            _job(
                "Nutmeg-AM数据入库",
                argv=[
                    "uv",
                    "run",
                    "python",
                    "scripts/openclaw/nutmeg_scheduler_ops.py",
                    "run-strict",
                    "--stage",
                    "close",
                ],
            )
        ],
        [
            _job(
                "Unrelated job",
                argv=[
                    "uv",
                    "run",
                    "python",
                    "scripts/openclaw/nutmeg_scheduler_ops.py",
                    "run-strict",
                    "--stage",
                    "unknown",
                ],
            )
        ],
        [
            _job(
                "Unrelated job",
                argv=[
                    "uv",
                    "run",
                    "python",
                    "scripts/openclaw/nutmeg_scheduler_ops.py",
                    "run-strict",
                    "--stage",
                    "am",
                    "--enable",
                ],
            )
        ],
        [
            _job(
                "Unrelated job",
                argv=[
                    "sh",
                    "-lc",
                    "uv run python scripts/openclaw/nutmeg_scheduler_ops.py "
                    "run-strict --stage am --enable",
                ],
            )
        ],
    ],
)
def test_unknown_or_inconsistent_nutmeg_job_fails_closed(
    jobs: list[dict[str, object]],
) -> None:
    result = OperatorMaintenanceProbe(
        runner=_Runner(_responses(jobs)), heartbeat_service=_heartbeat()
    ).read(as_of=AT)

    assert result.diagnostic_state == "diagnostic_unavailable"
    assert result.claims == []
    assert result.stages == []


@pytest.mark.parametrize(
    "first",
    [
        subprocess.TimeoutExpired("openclaw", 5),
        _completed(b"{}", returncode=1),
        _completed(b"not-json"),
        _completed(b"x" * 262_145),
        _completed("not bytes"),
    ],
)
def test_probe_failure_is_unavailable_not_owner_absence(
    first: SimpleNamespace | BaseException,
) -> None:
    result = OperatorMaintenanceProbe(runner=_Runner([first]), heartbeat_service=_heartbeat()).read(
        as_of=AT
    )

    assert result.diagnostic_state == "diagnostic_unavailable"
    assert result.claims == []
    assert result.stages == []
    assert result.diagnostic_code == "diagnostic_unavailable"


@pytest.mark.parametrize(
    "responses",
    [
        [_cron([]), _completed(b"not-json")],
        [_cron([]), _telegram(), _completed(b"missing", returncode=113)],
        [
            _cron([]),
            _telegram(),
            _completed(b"gui/501/com.nutmeg.unknown = {\nstate = running\n}\n"),
        ],
        [_cron([]), _telegram(), _completed(b"ok", stderr=b"x" * 262_145)],
    ],
)
def test_any_bounded_probe_failure_invalidates_the_whole_diagnostic(
    responses: list[SimpleNamespace],
) -> None:
    result = OperatorMaintenanceProbe(
        runner=_Runner(responses), heartbeat_service=_heartbeat()
    ).read(as_of=AT)

    assert result.diagnostic_state == "diagnostic_unavailable"
    assert result.claims == []
    assert result.stages == []


def test_duplicate_nutmeg_transport_accounts_fail_closed() -> None:
    account = {
        "accountId": "nutmeg",
        "configured": True,
        "running": True,
        "connected": True,
    }
    responses = [_cron([]), _telegram(accounts=[account, account])]

    result = OperatorMaintenanceProbe(
        runner=_Runner(responses), heartbeat_service=_heartbeat()
    ).read(as_of=AT)

    assert result.diagnostic_state == "diagnostic_unavailable"


def test_unknown_heartbeat_status_fails_closed() -> None:
    heartbeat = _heartbeat(available=False, blocking_code="provider diagnostic detail")

    result = OperatorMaintenanceProbe(
        runner=_Runner(_responses([])), heartbeat_service=heartbeat
    ).read(as_of=AT)

    assert result.diagnostic_state == "diagnostic_unavailable"
    assert "provider diagnostic detail" not in result.model_dump_json()


def test_runner_receives_only_fixed_bounded_non_shell_argv() -> None:
    runner = _Runner(_responses([]))

    OperatorMaintenanceProbe(runner=runner, heartbeat_service=_heartbeat()).read(as_of=AT)

    assert [call[0] for call in runner.calls] == [
        OPENCLAW_CRON_ARGV,
        OPENCLAW_TELEGRAM_ARGV,
        *[["launchctl", "print", f"gui/{os.getuid()}/{label}"] for label in LAUNCHD_LABELS],
    ]
    assert all(
        call[1]
        == {
            "capture_output": True,
            "check": False,
            "shell": False,
            "timeout": 5,
        }
        for call in runner.calls
    )


def test_telegram_selects_only_nutmeg_and_strips_sensitive_fields() -> None:
    accounts = [
        {
            "accountId": "other",
            "configured": True,
            "running": False,
            "connected": False,
            "tokenStatus": "secret-other",
        },
        {
            "accountId": "nutmeg",
            "configured": True,
            "running": True,
            "connected": False,
            "lastConnectedAt": 1_788_545_715_853,
            "lastStartAt": 1_788_537_894_212,
            "lastTransportActivityAt": 1_788_545_700_000,
            "tokenSource": "secret-value",
            "lastError": "diagnostic detail",
            "chatId": "123456",
        },
    ]
    responses = [_cron([]), _telegram(accounts=accounts)]
    responses.extend(_launchd(label) for label in LAUNCHD_LABELS)
    heartbeat = _heartbeat()

    result = OperatorMaintenanceProbe(runner=_Runner(responses), heartbeat_service=heartbeat).read(
        as_of=AT
    )

    assert result.telegram_transport.configured is True
    assert result.telegram_transport.running is True
    assert result.telegram_transport.connected is False
    assert result.telegram_owner.heartbeat_state == "available"
    assert result.telegram_owner.confirmation_available is True
    assert heartbeat.calls == [AT]
    serialized = result.model_dump_json()
    for secret in (
        "secret-value",
        "secret-other",
        "diagnostic detail",
        "123456",
        "payload",
        "raw_json",
    ):
        assert secret not in serialized


def test_maintenance_contract_rejects_unexpected_raw_diagnostic_fields() -> None:
    result = OperatorMaintenanceProbe(
        runner=_Runner(_responses([])), heartbeat_service=_heartbeat()
    ).read(as_of=AT)
    payload = result.model_dump(mode="json")
    payload["raw_json"] = {"token": "secret"}

    with pytest.raises(ValidationError):
        type(result).model_validate(payload)

    payload = result.model_dump(mode="json")
    payload["stages"][0]["claim_count"] += 1
    with pytest.raises(ValidationError):
        type(result).model_validate(payload)


def test_probe_does_not_write_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.rglob("*"))

    result = OperatorMaintenanceProbe(
        runner=_Runner(_responses([])), heartbeat_service=_heartbeat()
    ).read(as_of=AT)

    assert result.diagnostic_state == "available"
    assert tuple(tmp_path.rglob("*")) == before


def _ontology_counts(engine) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        tables = (schema.actions, sw.outbox_events, sf.tickets, sf.cash_transactions)
        return tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0) for table in tables
        )


def test_probe_does_not_write_actions_outbox_tickets_or_cash(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    heartbeat = TelegramOwnerHeartbeatService(
        action_service=ActionService(lambda: OntologyUnitOfWork(engine)),
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    before = _ontology_counts(engine)

    result = OperatorMaintenanceProbe(
        runner=_Runner(_responses([])), heartbeat_service=heartbeat
    ).read(as_of=AT)

    assert result.diagnostic_state == "available"
    assert result.telegram_owner.heartbeat_state == "missing"
    assert _ontology_counts(engine) == before


class _MaintenanceQuery:
    def __init__(self) -> None:
        self.calls: list[datetime] = []

    def read(self, *, as_of: datetime) -> object:
        self.calls.append(as_of)
        return object()


def test_operator_query_service_delegates_maintenance_read_only() -> None:
    maintenance = _MaintenanceQuery()
    queries = OperatorQueryService(
        repository=SimpleNamespace(),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: AT,
        maintenance_probe=maintenance,
    )

    result = queries.maintenance(as_of=AT)

    assert result is not None
    assert maintenance.calls == [AT]


def test_operator_query_service_does_not_invent_a_missing_maintenance_probe() -> None:
    queries = OperatorQueryService(
        repository=SimpleNamespace(),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: AT,
    )

    with pytest.raises(ProductNotFoundError, match="diagnostic is unavailable"):
        queries.maintenance(as_of=AT)
