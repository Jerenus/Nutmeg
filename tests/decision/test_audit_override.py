import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def _payload(*, complete_override: bool = True) -> dict:
    return {
        "issue": "26111",
        "prescription": {"12": "31"},
        "deviation_registry": [{
            "match_no": 12,
            "rule_ids": ["m-单选", "conf", "p-翻车场"],
            "reason": "Jun knowingly rejects the structural insurance findings.",
            "user_override": complete_override,
        }],
        "legs": {"12": {
            "name": "Real Madrid-Real Sociedad",
            "faces": "3",
            "fair": {"home": 0.70, "draw": 0.18, "away": 0.12},
            "confidence": 3,
            "directional_flags": [["anchor_shield_out", "1"]],
            "anchor_integrity": "fail",
        }},
    }


def _setup(tmp_path: Path, *, complete_override: bool = True):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    legs_file = tmp_path / "26111-legs.json"
    legs_file.write_text(
        json.dumps(_payload(complete_override=complete_override)),
        encoding="utf-8",
    )
    return kernel, data_dir, legs_file


def _invoke(
    data_dir: Path,
    legs_file: Path,
    *,
    override: bool,
    ticket_batch_token: str | None = None,
):
    args = [
        "decision-audit-legs",
        "--legs-file",
        str(legs_file),
        "--data-dir",
        str(data_dir),
    ]
    if override:
        args.append("--user-override")
    if ticket_batch_token is not None:
        args.extend(("--ticket-batch-token", ticket_batch_token))
    return CliRunner().invoke(app, args)


def test_default_audit_keeps_errors_blocking_and_writes_no_adjudication(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path)

    result = _invoke(data_dir, legs_file, override=False)

    assert result.exit_code == 1
    assert "flagged_naked_single" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0


def test_user_override_requires_a_signed_ticket_batch_token(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path)

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 1
    assert "--ticket-batch-token" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0


def test_user_override_without_batch_token_stays_blocked_before_registration(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path, complete_override=False)

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 1
    assert "--ticket-batch-token" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0


def test_user_override_prevalidates_all_matches_before_any_action(tmp_path):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    payload = _payload(complete_override=False)
    payload["prescription"]["10"] = "31"
    payload["deviation_registry"].append({
        "match_no": 10,
        "rule_ids": ["conf"],
        "reason": "complete earlier override",
        "user_override": True,
    })
    payload["legs"]["10"] = {
        "name": "Home-Away",
        "faces": "3",
        "fair": {"home": 0.60, "draw": 0.25, "away": 0.15},
        "confidence": 3,
    }
    legs_file = tmp_path / "two-match-legs.json"
    legs_file.write_text(json.dumps(payload), encoding="utf-8")

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 1
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
