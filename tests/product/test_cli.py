from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import product as product_cli
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.wiring import build_product_services


def test_product_services_refuse_uninitialized_kernel(tmp_path: Path) -> None:
    with pytest.raises(ProductNotReadyError, match="ontology is not initialized"):
        build_product_services(AppSettings(data_dir=tmp_path / "data"))


def test_product_services_compose_only_current_kernel(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    build_ontology_kernel(settings).initialize()

    services = build_product_services(settings)

    assert services.kernel.status().integrity_check == "ok"
    assert services.queries.health().ontology_schema_version == MIGRATIONS[-1].version
    assert services.settings is settings


def test_app_command_binds_loopback_by_default(monkeypatch, tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    build_ontology_kernel(settings).initialize()
    captured: dict[str, object] = {}
    monkeypatch.setattr(product_cli._cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda application, host, port: captured.update(
            {"app": application, "host": host, "port": port}
        ),
    )

    result = CliRunner().invoke(app, ["app"])

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8788
