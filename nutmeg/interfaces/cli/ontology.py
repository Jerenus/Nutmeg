"""``nutmeg ontology`` — kernel init/status operations (Package 1).

``init`` applies migrations and is idempotent; ``status`` is strictly read-only
and never initializes the database. ``status`` exits non-zero when the kernel is
uninitialized or its integrity check is not ``ok``, so it doubles as a health
gate. Every CLI-package global is reached through ``_cli`` to preserve the test
monkeypatch conventions.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli

ontology_app = _cli.typer.Typer(help="Ontology Kernel v2 operations")
_cli.app.add_typer(ontology_app, name="ontology")


def _require_format(fmt: str) -> None:
    if fmt not in ("text", "json"):
        _cli.typer.echo(f"invalid --format {fmt!r}: expected 'text' or 'json'", err=True)
        raise _cli.typer.Exit(code=2)


@ontology_app.command("init")
def ontology_init(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _require_format(format)
    settings = _cli.get_settings()
    kernel = _cli.build_ontology_kernel(settings)
    report = kernel.initialize()
    status = kernel.status()
    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(
                {
                    "applied_versions": list(report.applied_versions),
                    "schema_version": status.schema_version,
                    "ontology_db_path": str(settings.ontology_db_path),
                    "ontology_artifact_dir": str(settings.ontology_artifact_dir),
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return
    _cli.console.print(
        f"ontology initialized: applied={list(report.applied_versions)} "
        f"schema_version={status.schema_version}"
    )
    _cli.console.print(f"db={settings.ontology_db_path}")
    _cli.console.print(f"artifacts={settings.ontology_artifact_dir}")


@ontology_app.command("status")
def ontology_status(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _require_format(format)
    settings = _cli.get_settings()
    status = _cli.build_ontology_kernel(settings).status()
    healthy = status.initialized and status.integrity_check == "ok"
    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(status.to_dict(), indent=2, sort_keys=True, default=str)
        )
    else:
        _cli.console.print(
            f"ontology initialized={status.initialized} "
            f"schema_version={status.schema_version} integrity={status.integrity_check}"
        )
    raise _cli.typer.Exit(code=0 if healthy else 1)
