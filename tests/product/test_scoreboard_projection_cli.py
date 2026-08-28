import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import ActorRole, ObjectRef, canonical_json
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _invoke(*args: str):
    return CliRunner().invoke(app, ["scoreboard", *args])


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert result.stdout.strip() == canonical_json(payload)
    return payload


def _observe(kernel, *, metric_key: str, key: str) -> None:
    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="chains",
            metric_key=metric_key,
            tally="1/1",
            detail=f"formal manual observation {metric_key}",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("adjudication", f"adj-{metric_key}")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT,
        )
    )


def _action_watermark(kernel) -> int:
    with OntologyUnitOfWork(kernel.engine) as uow:
        value = uow.connection.exec_driver_sql(
            "SELECT max(rowid) FROM actions"
        ).scalar_one()
    return int(value or 0)


def _shadow_args(
    data_dir: Path,
    legacy: Path,
    classification: Path,
    watermark: int,
) -> list[str]:
    return [
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
        str(watermark),
        "--requested-at",
        AT.isoformat(),
        "--acknowledge-manual-source",
    ]


def test_rebuild_projection_refreshes_stale_shadow_without_action_write(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    _observe(kernel, metric_key="main", key="rebuild:main")

    first_before = _action_watermark(kernel)
    first = _json(
        _invoke(
            "rebuild-projection",
            "--data-dir",
            str(data_dir),
            "--as-of",
            AT.isoformat(),
            "--built-at",
            "2026-08-24T10:05:00+00:00",
        )
    )
    assert first["status"] == "succeeded"
    assert first["projection_version"] == "sb-v1"
    assert first["source_high_watermark"] == first_before
    assert _action_watermark(kernel) == first_before

    legacy = tmp_path / "scoreboard.json"
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

    _observe(kernel, metric_key="later", key="rebuild:later")
    stale = _invoke(*_shadow_args(data_dir, legacy, classification, first_before))
    assert stale.exit_code == 1
    assert "projection is stale" in stale.stdout

    second_before = _action_watermark(kernel)
    second = _json(
        _invoke(
            "rebuild-projection",
            "--data-dir",
            str(data_dir),
            "--as-of",
            AT.isoformat(),
            "--built-at",
            "2026-08-24T10:10:00+00:00",
        )
    )
    assert second["source_high_watermark"] == second_before
    assert _action_watermark(kernel) == second_before

    shadow = _json(
        _invoke(
            *_shadow_args(
                data_dir,
                legacy,
                classification,
                int(second["source_high_watermark"]),
            )
        )
    )
    assert shadow["status"] == "committed"


def test_rebuild_projection_rejects_naive_time_and_uninitialized_root(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    naive = _invoke(
        "rebuild-projection",
        "--data-dir",
        str(data_dir),
        "--as-of",
        "2026-08-24T10:00:00",
        "--built-at",
        AT.isoformat(),
    )
    assert naive.exit_code == 1
    assert "timestamp must be timezone-aware" in naive.stdout

    absent = _invoke(
        "rebuild-projection",
        "--data-dir",
        str(tmp_path / "absent"),
        "--as-of",
        AT.isoformat(),
        "--built-at",
        AT.isoformat(),
    )
    assert absent.exit_code == 1
    assert "ontology must be initialized" in absent.stdout
