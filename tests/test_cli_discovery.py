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


def test_iteration_timeline_is_read_only_on_empty_old_and_current_stores(tmp_path):
    absent = tmp_path / "absent"
    result = runner.invoke(app, ["discovery", "iteration", "--data-dir", str(absent)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["contract_status"] == "approved"
    assert payload["pending_human_approval"] is False
    assert payload["runtime_authority"] is False
    assert "contract_unapproved" not in payload["trigger_blocks"]
    assert "no_store" in payload["trigger_blocks"]
    assert not absent.exists()

    old = tmp_path / "old"
    database = OntologyPaths.from_data_dir(old).database
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (39)")
    before = database.read_bytes()
    result = runner.invoke(app, ["discovery", "iteration", "--data-dir", str(old)])
    assert result.exit_code == 1
    assert database.read_bytes() == before

    current = tmp_path / "current"
    kernel = build_ontology_kernel(AppSettings(data_dir=current))
    kernel.initialize()
    database = OntologyPaths.from_data_dir(current).database
    before = database.read_bytes()
    result = runner.invoke(app, ["discovery", "iteration", "--data-dir", str(current)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["effective_new_clusters"] == 0
    assert database.read_bytes() == before


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


def test_promotion_on_schema_42_requires_receipts_without_migrating(tmp_path):
    data_dir = tmp_path / "old"
    database = OntologyPaths.from_data_dir(data_dir).database
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (42)")
    before = database.read_bytes()
    result = runner.invoke(app, ["discovery", "promotion", "--data-dir", str(data_dir)])
    assert result.exit_code == 1
    assert "migration 43 required" in result.output
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
    jczq = tmp_path / "jczq"
    day = "2026-09-21"
    shadow = tmp_path / "shadow.db"
    result = runner.invoke(
        app,
        [
            "discovery",
            "shadow-run",
            "--source-day",
            day,
            "--jczq-dir",
            str(jczq),
            "--shadow-db",
            str(shadow),
            "--cutoff-at",
            "2026-09-21T07:00:00+00:00",
        ],
    )
    assert result.exit_code != 0
    assert "approval" in result.output.lower()
    assert not jczq.exists()
    assert not shadow.exists()


def test_shadow_run_rejects_mismatched_scope_without_creating_store(tmp_path):
    jczq = tmp_path / "jczq"
    day = "2026-09-21"
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
            "--source-day",
            day,
            "--jczq-dir",
            str(jczq),
            "--shadow-db",
            str(shadow),
            "--cutoff-at",
            "2026-09-21T07:00:00+00:00",
            "--approval-file",
            str(approval),
        ],
    )
    assert result.exit_code == 1
    assert "scope" in result.output
    assert not jczq.exists()
    assert not shadow.exists()


def test_shadow_run_rejects_expired_prospective_cutoff(tmp_path):
    jczq = tmp_path / "jczq"
    day = "2026-09-04"
    source = jczq / "daily" / day
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
                    "generation_request_id": f"day:{day}",
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
            "--source-day",
            day,
            "--jczq-dir",
            str(jczq),
            "--shadow-db",
            str(shadow),
            "--cutoff-at",
            cutoff,
            "--approval-file",
            str(approval),
        ],
    )
    assert result.exit_code == 1
    assert "expired" in result.output
    assert not jczq.exists() and not shadow.exists()


def test_register_baseline_creates_shadow_store_and_registers_incumbent(tmp_path):
    data_dir = tmp_path / "shadow"
    result = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(data_dir), "--by", "op:jun"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    artifact = load_baseline_policy(
        Path(__file__).resolve().parents[1]
        / "experiments/discovery/structural-baseline-v1.policy.json"
    )
    assert payload["policy_revision_id"] == "structural-baseline-v1"
    assert payload["source_artifact_hash"] == canonical_hash(artifact.model_dump(mode="json"))
    status = runner.invoke(app, ["discovery", "status", "--data-dir", str(data_dir)])
    assert status.exit_code == 0, status.output
    assert "incumbent: none" in status.output
    shown = runner.invoke(
        app,
        [
            "discovery", "show", "--kind", "policy", "--id", "structural-baseline-v1",
            "--data-dir", str(data_dir),
        ],
    )
    assert shown.exit_code == 0, shown.output
    policy = json.loads(shown.output)["policy"]
    assert policy["created_by"] == "op:jun"
    assert policy["validation_result"]["valid"] is True
    assert policy["generator_family"] == "baseline"
    again = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(data_dir), "--by", "op:jun"]
    )
    assert again.exit_code in {0, 1}, again.output
    if again.exit_code == 1:
        assert "already registered" in again.output


def test_register_baseline_refuses_production_data_directory(monkeypatch, tmp_path):
    import nutmeg.interfaces.cli.discovery as discovery_cli

    production = tmp_path / "prod-data"
    production.mkdir()
    monkeypatch.setattr(discovery_cli, "PRODUCTION_DATA_DIR", production)
    result = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(production), "--by", "op:jun"]
    )
    assert result.exit_code == 1
    assert "production data directory" in result.output
    assert not (production / "ontology").exists()


class _FrozenDatetime:
    """Pin `now` so the prospective-cutoff window check does not depend on wall time."""

    from datetime import datetime as _real

    @classmethod
    def now(cls, tz=None):
        return cls._real(2026, 9, 22, 8, 0, tzinfo=tz)

    @classmethod
    def fromisoformat(cls, value):
        return cls._real.fromisoformat(value)


def test_shadow_run_refuses_shadow_store_inside_production_data_directory(monkeypatch, tmp_path):
    import nutmeg.interfaces.cli.discovery as discovery_cli

    production = tmp_path / "prod-data"
    (production / "ontology").mkdir(parents=True)
    jczq = production / "jczq"
    day = "2026-09-22"
    source = jczq / "daily" / day
    shadow = production / "archive" / "shadow.db"
    monkeypatch.setattr(discovery_cli, "PRODUCTION_DATA_DIR", production)
    monkeypatch.setattr(discovery_cli, "datetime", _FrozenDatetime)
    cutoff = "2026-09-22T07:00:00+00:00"
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "approval_id": "approval-1",
                "approved_by": "op:jun",
                "approved_at": "2026-09-22T06:00:00+00:00",
                "scope": {
                    "source_db": str(source.resolve()),
                    "shadow_db": str(shadow.resolve()),
                    "generation_request_id": f"day:{day}",
                    "cutoff_at": cutoff,
                    "policy_revision_id": "structural-baseline-v1",
                },
            }
        )
    )
    result = runner.invoke(
        app,
        [
            "discovery", "shadow-run", "--source-day", day, "--jczq-dir", str(jczq),
            "--shadow-db", str(shadow),
            "--cutoff-at", cutoff, "--approval-file", str(approval),
        ],
    )
    assert result.exit_code == 1
    assert "production data directory" in result.output
    assert not source.exists() and not shadow.exists()


def _prospective_day_fixture(tmp_path):
    """Build today's day directory with reads/quotes captured a few minutes ago (BJT).

    `shadow-run` checks `cutoff <= now` and `approved_at <= cutoff` against the real wall
    clock, so the fixture must sit on today's business day with every reference (reads,
    quotes and the board file's mtime) captured before a cutoff of `now - 1 minute`.
    """
    import os
    from datetime import UTC, datetime, timedelta, timezone

    from tests.discovery.test_day_inputs import _day

    bj = timezone(timedelta(hours=8))
    now = datetime.now(UTC)
    captured = (now - timedelta(minutes=3)).astimezone(bj).replace(microsecond=0)
    day = captured.strftime("%Y-%m-%d")
    jczq = _day(
        tmp_path,
        day=day,
        made_at=captured.isoformat(),
        quote_date=day,
        quote_time=captured.strftime("%H:%M:%S"),
    )
    day_dir = jczq / "daily" / day
    for name in ("jczq-legs-base.json", "reads.json", "sporttery_markets.json"):
        os.utime(day_dir / name, (captured.timestamp(), captured.timestamp()))
    cutoff = (now - timedelta(minutes=1)).replace(microsecond=0)
    approved_at = (now - timedelta(minutes=2)).replace(microsecond=0)
    return jczq, day, day_dir, cutoff.isoformat(), approved_at.isoformat()


def test_shadow_run_source_day_records_a_sealed_world(tmp_path):
    from nutmeg.discovery.day_inputs import day_fingerprint

    jczq, day, day_dir, cutoff, approved_at = _prospective_day_fixture(tmp_path)
    shadow_dir = tmp_path / "shadow"
    registered = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(shadow_dir), "--by", "op:jun"]
    )
    assert registered.exit_code == 0, registered.output
    shadow_db = OntologyPaths.from_data_dir(shadow_dir).database
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "approval_id": "approval-day-1",
                "approved_by": "op:jun",
                "approved_at": approved_at,
                "scope": {
                    "source_db": str(day_dir.resolve()),
                    "shadow_db": str(shadow_db.resolve()),
                    "generation_request_id": f"day:{day}",
                    "cutoff_at": cutoff,
                    "policy_revision_id": "structural-baseline-v1",
                },
            }
        ),
        encoding="utf-8",
    )
    before = day_fingerprint(day_dir)
    result = runner.invoke(
        app,
        [
            "discovery", "shadow-run", "--source-day", day, "--jczq-dir", str(jczq),
            "--shadow-db", str(shadow_db), "--cutoff-at", cutoff,
            "--approval-file", str(approval),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["world_id"] and payload["sealed_manifest_hash"]
    assert payload["approval_id"] == "approval-day-1"
    assert day_fingerprint(day_dir) == before  # the day's files were not written
    status = runner.invoke(app, ["discovery", "status", "--data-dir", str(shadow_dir)])
    assert status.exit_code == 0, status.output
    assert "sealed worlds: 1" in status.output
    assert f"latest world: {payload['world_id']}" in status.output


def test_shadow_run_requires_a_source(tmp_path):
    shadow = tmp_path / "shadow.db"
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "discovery", "shadow-run", "--shadow-db", str(shadow),
            "--cutoff-at", "2026-09-23T04:00:00+00:00", "--approval-file", str(approval),
        ],
    )
    assert result.exit_code != 0
    assert "--source-day" in result.output
    assert "missing option" in result.output.lower()
    assert not shadow.exists()


def _standing_file(tmp_path, jczq, shadow_db):
    from datetime import UTC, datetime, timedelta

    approved = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    path = tmp_path / "standing.json"
    path.write_text(
        json.dumps(
            {
                "approval_id": "standing-cli",
                "kind": "standing",
                "approved_by": "op:jun",
                "approved_at": approved,
                "valid_from": approved,
                "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "revoked_at": None,
                "scope_template": {
                    "source_kind": "day",
                    "jczq_dir": str(jczq),
                    "shadow_db": str(shadow_db),
                    "policy_revision_id": "structural-baseline-v1",
                    "generation_request_pattern": "day:{business_date}",
                    "cutoff_window_bjt": ["00:00", "23:59"],
                    "max_worlds_per_business_date": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_nightly_records_one_world_under_a_standing_approval_then_skips(tmp_path):
    jczq, day, _day_dir, _cutoff, _approved = _prospective_day_fixture(tmp_path)
    shadow_dir = tmp_path / "shadow"
    registered = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(shadow_dir), "--by", "op:jun"]
    )
    assert registered.exit_code == 0, registered.output
    shadow_db = OntologyPaths.from_data_dir(shadow_dir).database
    standing = _standing_file(tmp_path, jczq, shadow_db)
    args = [
        "discovery", "nightly", "--day", day, "--jczq-dir", str(jczq),
        "--shadow-db", str(shadow_db), "--standing-approval", str(standing),
        "--reports-dir", str(tmp_path / "reports"), "--tickets-dir", str(tmp_path / "tickets"),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout.strip().splitlines()[-1])
    assert payload["status"] == "recorded" and payload["world_id"], payload
    status = runner.invoke(app, ["discovery", "status", "--data-dir", str(shadow_dir)])
    assert "sealed worlds: 1" in status.output
    second = runner.invoke(app, args)
    assert second.exit_code == 0
    assert json.loads(second.stdout.strip().splitlines()[-1])["reason"] == "already_recorded"


def test_nightly_refuses_a_shadow_store_inside_production(monkeypatch, tmp_path):
    import nutmeg.interfaces.cli.discovery as discovery_cli

    production = tmp_path / "prod-data"
    (production / "ontology").mkdir(parents=True)
    monkeypatch.setattr(discovery_cli, "PRODUCTION_DATA_DIR", production)
    result = runner.invoke(
        app,
        ["discovery", "nightly", "--day", "2026-09-29",
         "--shadow-db", str(production / "ontology" / "ontology.db")],
    )
    assert result.exit_code == 1 and "production data directory" in result.output


def test_compare_scores_a_recorded_night_and_appends_the_ledger_once(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    book = {
        "A": {"belief": {"3": 0.5, "1": 0.3, "0": 0.2}, "odds": {"3": 1.8, "1": 3.2, "0": 4.5}},
        "C": {"belief": {"3": 0.7, "1": 0.2, "0": 0.1}, "odds": {"3": 1.3, "1": 4.6, "0": 8.0}},
    }
    (reports / "2026-09-29.json").write_text(
        json.dumps(
            {
                "day": "2026-09-29", "status": "recorded", "world_id": "w", "manifest_hash": "m",
                "offer_book": book, "band_best": {}, "ticket_snapshot": {"betslips": []},
                "decision_rule_best": {
                    "legs": [{"code": "A", "faces": "3"}, {"code": "C", "faces": "3"}],
                    "p_belief": 0.35, "notes": 1, "modal_return_per_yuan": 2.34,
                },
            }
        ),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    results = data / "daily" / "2026-09-30" / "results-90.json"
    results.parent.mkdir(parents=True)
    results.write_text(
        json.dumps({"A": {"outcome_90": "3"}, "C": {"outcome_90": "1"}}), encoding="utf-8"
    )
    args = ["discovery", "compare", "--day", "2026-09-29", "--data-dir", str(data),
            "--reports-dir", str(reports)]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    out = json.loads(first.stdout.strip().splitlines()[-1])
    assert out["status"] == "settled"
    assert {row["kind"] for row in out["rows"]} == {"decision_rule", "empty"}
    assert out["summary"]["n_days"] == 1
    runner.invoke(app, args)
    ledger = data / "analytics" / "dream-compare" / "ledger.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_compare_without_a_recorded_night_is_a_quiet_no_world(tmp_path):
    result = runner.invoke(
        app,
        ["discovery", "compare", "--day", "2026-09-29", "--data-dir", str(tmp_path / "data"),
         "--reports-dir", str(tmp_path / "reports")],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == "no_world"
