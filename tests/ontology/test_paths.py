from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.paths import OntologyPaths


def test_settings_exposes_separate_ontology_paths(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    assert settings.ontology_dir == tmp_path / "data" / "ontology"
    assert settings.ontology_db_path == tmp_path / "data" / "ontology" / "ontology.db"
    assert settings.ontology_artifact_dir == tmp_path / "data" / "ontology" / "artifacts"
    assert settings.ontology_db_url.startswith("sqlite+pysqlite:///")


def test_ontology_paths_create_only_owned_directories(tmp_path: Path) -> None:
    paths = OntologyPaths.from_data_dir(tmp_path / "data")
    paths.ensure_directories()
    assert paths.root.is_dir()
    assert paths.artifacts.is_dir()
    assert not paths.database.exists()
