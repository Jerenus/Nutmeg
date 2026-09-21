from __future__ import annotations

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
