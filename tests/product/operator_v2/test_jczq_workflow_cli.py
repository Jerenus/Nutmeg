from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import workflow as workflow_cli
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_cutover import JczqCutoverGate
from nutmeg.product.jczq_replay import JczqReplayRunner


def _write_accepted_replay_inputs(root) -> None:
    day_root = root / "jczq" / "daily" / "2026-09-19"
    day_root.mkdir(parents=True)
    matches = []
    reads = []
    for index in range(1, 31):
        code = f"周六{index:03d}"
        matches.append(
            {
                "matchId": 2_000_000 + index,
                "matchNumStr": code,
                "matchDate": "2026-09-19",
                "matchTime": "23:00:00",
            }
        )
        reads.append(
            {
                "read_id": f"read-{index}",
                "match_id": f"legacy-match-{index}",
                "made_at": "2026-09-19T12:00:00+08:00",
                "status": "draft",
            }
        )
    (day_root / "sporttery_markets.json").write_text(
        json.dumps(
            {
                "lastUpdateTime": "2026-09-19 11:00:00",
                "matchInfoList": [
                    {"businessDate": "2026-09-19", "subMatchList": matches}
                ],
            }
        ),
        encoding="utf-8",
    )
    (day_root / "reads.json").write_text(json.dumps(reads), encoding="utf-8")
    for index in tuple(item for item in range(1, 31) if item != 2)[:25]:
        (day_root / f"research-周六{index:03d}.json").write_text(
            json.dumps({"captured_at": "2026-09-19T11:03:42+08:00"}),
            encoding="utf-8",
        )
    (day_root / "research-周六002.rejected.json").write_text(
        json.dumps({"error": "canonical intake rejected"}), encoding="utf-8"
    )
    (day_root / "results.json").write_text(
        json.dumps(
            {
                "published_at": "2026-09-20T12:00:00+08:00",
                "results": [
                    {
                        "match_id": f"jczq-sporttery-{2_000_000 + index}",
                        "score_90": "2-1",
                        "status": "final",
                    }
                    for index in range(1, 31)
                ],
            }
        ),
        encoding="utf-8",
    )


def _accepted_replay(tmp_path):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    kernel.engine.dispose()
    _write_accepted_replay_inputs(data_dir)
    isolated = tmp_path / "isolated"
    report = JczqReplayRunner(
        source_root=data_dir, isolated_root=isolated
    ).run("2026-09-19")
    assert report.accepted is True
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    gate = JczqCutoverGate(service, schema_version=kernel.status().schema_version)
    return gate, isolated / "replay-2026-09-19.json"


def test_cutover_refuses_without_accepted_replay(tmp_path) -> None:
    report = tmp_path / "replay.json"
    report.write_text(json.dumps({"accepted": False}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "jczq-cutover",
            "--day",
            "2026-09-20",
            "--replay-report",
            str(report),
            "--check-only",
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )

    assert result.exit_code == 1
    assert "accepted replay is required" in result.stdout


def test_jczq_status_calls_the_authoritative_product_query(tmp_path, monkeypatch) -> None:
    calls = []

    class _Service:
        def status(self, day):
            calls.append(day)
            return {"business_date": day, "authority": "legacy_read_only"}

    monkeypatch.setattr(workflow_cli, "_jczq_workflow_service", lambda _data: _Service())

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "jczq-status",
            "--day",
            "2026-09-20",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["2026-09-20"]
    assert json.loads(result.stdout)["authority"] == "legacy_read_only"


def test_cutover_action_requires_valid_zero_side_effect_report(tmp_path) -> None:
    gate, report = _accepted_replay(tmp_path)

    checked = gate.check("2026-09-20", report)
    approved = gate.approve(
        "2026-09-20",
        report,
        actor_id="operator:jun",
        requested_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert checked.authority == "legacy_read_only"
    assert approved.authority == "ontology_v2_required"
    assert gate.authority() == "ontology_v2_required"


def test_cutover_refuses_report_from_the_wrong_replay_day(tmp_path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    gate = JczqCutoverGate(service, schema_version=kernel.status().schema_version)
    document = {
        "day": "2026-09-18",
        "schema_version": kernel.status().schema_version,
        "board_count": 30,
        "research_terminal_count": 30,
        "missing_lineage": [],
        "odds_band_outcomes": ["10x", "20x", "50x", "100x"],
        "terminal_kind": "no_ticket",
        "failures": [],
        "accepted": True,
        "production_delta": {
            "objects": 0,
            "money_entries": 0,
            "dispatches": 0,
            "prospective_observations": 0,
        },
    }
    document["report_sha256"] = hashlib.sha256(
        canonical_json(document).encode("utf-8")
    ).hexdigest()
    report = tmp_path / "accepted.json"
    report.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="replay day is not the approved gate day"):
        gate.check("2026-09-20", report)


def test_cutover_revalidates_accepted_report_contract(tmp_path) -> None:
    gate, report = _accepted_replay(tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    document["board_count"] = 29
    document["report_sha256"] = hashlib.sha256(
        canonical_json(
            {key: value for key, value in document.items() if key != "report_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    report.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="isolated replay run"):
        gate.check("2026-09-20", report)
