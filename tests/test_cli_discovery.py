from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.discovery.contracts import load_baseline_policy
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.test_discovery_policy_actions import _registration
from tests.ontology.test_discovery_world_actions import _request

runner = CliRunner()


def test_discovery_status_is_read_only_and_empty_on_fresh_store(tmp_path):
    data_dir = tmp_path / "absent"
    result = runner.invoke(app, ["discovery", "status", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "incumbent: none" in result.output
    assert "sealed worlds: 0" in result.output
    assert not data_dir.exists()


def test_discovery_show_unknown_object_fails_without_mutation(tmp_path):
    data_dir = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["discovery", "show", "--kind", "world", "--id", "missing", "--data-dir", str(data_dir)],
    )
    assert result.exit_code == 1
    assert "not found" in result.output
    assert not data_dir.exists()


def test_generation_show_on_schema_40_is_read_only_and_explicit(tmp_path):
    data_dir = tmp_path / "old"
    database = OntologyPaths.from_data_dir(data_dir).database
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (40)")
    before = database.read_bytes()
    result = runner.invoke(
        app, ["discovery", "show", "--kind", "generation", "--id", "r", "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 1
    assert "migration 41 required" in result.output
    assert database.read_bytes() == before


def test_promotion_status_on_schema_41_is_read_only_and_explicit(tmp_path):
    data_dir = tmp_path / "old"
    database = OntologyPaths.from_data_dir(data_dir).database
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (41)")
    before = database.read_bytes()
    result = runner.invoke(app, ["discovery", "promotion", "--data-dir", str(data_dir)])
    assert result.exit_code == 1
    assert "promotion unavailable; migration 42 required" in result.output
    assert database.read_bytes() == before


def test_promotion_on_empty_store_is_read_only(tmp_path):
    data_dir = tmp_path / "absent"
    result = runner.invoke(app, ["discovery", "promotion", "--data-dir", str(data_dir)])
    assert result.exit_code == 0
    assert "incumbent" in result.output
    assert not data_dir.exists()


def test_generation_show_reports_receipt_without_mutation(tmp_path):
    from datetime import UTC, datetime

    from nutmeg.ontology.actions.discovery_policy_actions import RecordPolicyGenerationRoundRequest
    from nutmeg.ontology.actions.models import ActorRole
    from tests.ontology.test_discovery_generation_actions import _round

    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    receipt = kernel.discovery_policy_actions.record_generation_round(
        RecordPolicyGenerationRoundRequest(
            _round(),
            "sys:generator",
            ActorRole.DETERMINISTIC_SYSTEM,
            "generation:show",
            datetime(2026, 9, 22, tzinfo=UTC),
        )
    )
    assert receipt.status is ActionStatus.COMMITTED
    database = OntologyPaths.from_data_dir(data_dir).database
    before = database.read_bytes()
    result = runner.invoke(
        app,
        [
            "discovery",
            "show",
            "--kind",
            "generation",
            "--id",
            "round-1",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["generation_cost"] == {"attempts": 0}
    assert payload["candidate_hashes"] == []
    assert payload["trace_hash"] == canonical_hash({"attempts": [], "proposals": []})
    assert database.read_bytes() == before


def test_discovery_status_reads_registered_policy_and_shadow_world(tmp_path):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    artifact = load_baseline_policy(
        Path(__file__).resolve().parents[1]
        / "experiments/discovery/structural-baseline-v1.policy.json"
    ).model_dump(mode="json")
    request = _registration()
    policy = replace(
        request.policy,
        policy_revision_id=artifact["policy_revision_id"],
        family=artifact["family"],
        source_artifact_hash=canonical_hash(artifact),
        interface_version=artifact["interface_version"],
        constraints_version=artifact["constraints_version"],
        generator_family=artifact["generator_family"],
        compatible_world_families=artifact["compatible_world_families"],
    )
    assert (
        kernel.discovery_policy_actions.register_policy(
            replace(request, policy=policy, artifact=artifact)
        ).status
        is ActionStatus.COMMITTED
    )
    assert kernel.discovery_world_actions.create_world(_request()).status is ActionStatus.COMMITTED
    result = runner.invoke(
        app,
        [
            "discovery",
            "status",
            "--data-dir",
            str(data_dir),
            "--family",
            "structural_candidate_exploration",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "latest world: world-1" in result.output
    assert "sealed worlds: 0" in result.output
    assert "incumbent: none" in result.output


def test_discovery_status_does_not_migrate_old_schema(tmp_path):
    data_dir = tmp_path / "old"
    database = OntologyPaths.from_data_dir(data_dir).database
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (39)")
    before = database.read_bytes()
    result = runner.invoke(app, ["discovery", "status", "--data-dir", str(data_dir)])
    assert result.exit_code == 1
    assert "schema 40 is required" in result.output
    assert database.read_bytes() == before


def test_discovery_readiness_empty_store_is_read_only(tmp_path):
    data_dir = tmp_path / "missing"
    result = runner.invoke(app, ["discovery", "readiness", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "record_only"
    assert payload["metrics"]["branch_unavailable_rate"]["status"] == "unknown"
    assert not data_dir.exists()


def test_shadow_run_requires_separate_approval_without_creating_stores(tmp_path):
    source = tmp_path / "source.db"
    shadow = tmp_path / "shadow.db"
    result = runner.invoke(
        app,
        [
            "discovery",
            "shadow-run",
            "--source-db",
            str(source),
            "--shadow-db",
            str(shadow),
            "--generation-request-id",
            "request-1",
            "--cutoff-at",
            "2026-09-21T07:00:00+00:00",
        ],
    )
    assert result.exit_code != 0
    assert "approval" in result.output.lower()
    assert not source.exists()
    assert not shadow.exists()


def test_shadow_run_rejects_mismatched_scope_without_creating_store(tmp_path):
    source = tmp_path / "source.db"
    shadow = tmp_path / "shadow.db"
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "approval_id": "approval-1",
                "approved_by": "op:jun",
                "approved_at": "2026-09-21T06:00:00+00:00",
                "scope": {"source_db": "different"},
            }
        )
    )
    result = runner.invoke(
        app,
        [
            "discovery",
            "shadow-run",
            "--source-db",
            str(source),
            "--shadow-db",
            str(shadow),
            "--generation-request-id",
            "request-1",
            "--cutoff-at",
            "2026-09-21T07:00:00+00:00",
            "--approval-file",
            str(approval),
        ],
    )
    assert result.exit_code == 1
    assert "scope" in result.output
    assert not source.exists()
    assert not shadow.exists()


def test_shadow_run_rejects_expired_prospective_cutoff(tmp_path):
    source = tmp_path / "source.db"
    shadow = tmp_path / "shadow.db"
    approval = tmp_path / "approval.json"
    cutoff = "2026-09-04T07:00:00+00:00"
    approval.write_text(
        json.dumps(
            {
                "approval_id": "fixture-only",
                "approved_by": "fixture-operator",
                "approved_at": "2026-09-04T06:00:00+00:00",
                "scope": {
                    "source_db": str(source.resolve()),
                    "shadow_db": str(shadow.resolve()),
                    "generation_request_id": "request-1",
                    "cutoff_at": cutoff,
                    "policy_revision_id": "structural-baseline-v1",
                },
            }
        )
    )
    result = runner.invoke(
        app,
        [
            "discovery",
            "shadow-run",
            "--source-db",
            str(source),
            "--shadow-db",
            str(shadow),
            "--generation-request-id",
            "request-1",
            "--cutoff-at",
            cutoff,
            "--approval-file",
            str(approval),
        ],
    )
    assert result.exit_code == 1
    assert "expired" in result.output
    assert not source.exists() and not shadow.exists()
