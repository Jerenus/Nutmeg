import json

from typer.testing import CliRunner

from nutmeg.config.settings import get_settings
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_ontology_status_is_read_only_before_init() -> None:
    result = runner.invoke(app, ["ontology", "status", "--format", "json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["initialized"] is False
    assert not get_settings().ontology_db_path.exists()


