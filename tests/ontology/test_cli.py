import json

from typer.testing import CliRunner

from nutmeg.config.settings import get_settings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.repository.migrations import MIGRATIONS

runner = CliRunner()


def test_ontology_status_is_read_only_before_init() -> None:
    result = runner.invoke(app, ["ontology", "status", "--format", "json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["initialized"] is False
    assert not get_settings().ontology_db_path.exists()


def test_ontology_init_then_status_and_doctor() -> None:
    initialized = runner.invoke(app, ["ontology", "init", "--format", "json"])
    status = runner.invoke(app, ["ontology", "status", "--format", "json"])
    doctor = runner.invoke(app, ["doctor", "--format", "json"])
    assert initialized.exit_code == 0
    assert json.loads(initialized.stdout)["applied_versions"] == [
        migration.version for migration in MIGRATIONS
    ]
    assert status.exit_code == 0
    assert json.loads(status.stdout)["integrity_check"] == "ok"
    assert json.loads(doctor.stdout)["ontology"]["initialized"] is True
