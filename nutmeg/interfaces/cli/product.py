"""``nutmeg app`` — local Intelligence OS product service."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import nutmeg.interfaces.cli as _cli


def _warn_if_exposed(host: str) -> bool:
    if host in ('127.0.0.1', 'localhost', '::1'):
        return False
    print(
        f'WARNING: nutmeg app is binding {host}; v1 is a private single-user service.',
        file=sys.stderr,
    )
    return True


@_cli.app.command('app')
def product_app(
    host: str = _cli.typer.Option('127.0.0.1', '--host'),
    port: int = _cli.typer.Option(8788, '--port'),
    data_dir: Annotated[Path | None, _cli.typer.Option('--data-dir')] = None,
) -> None:
    """Launch the versioned local Intelligence OS application."""
    import uvicorn

    from nutmeg.interfaces.product_api import create_product_app
    from nutmeg.product.operator_runtime import (
        ApplicationInstanceLease,
        OntologyWriterLease,
        OperatorRuntimeError,
        probe_source_identity,
        validate_operator_runtime,
    )
    from nutmeg.product.wiring import build_product_services

    settings = _cli.get_settings()
    if data_dir is not None:
        settings = settings.model_copy(update={'data_dir': data_dir})
    app_lease = None
    writer_lease = None
    try:
        identity = probe_source_identity()
        runtime = validate_operator_runtime(
            settings,
            running_commit=identity.running_commit,
            dirty=identity.dirty,
            data_dir_was_explicit=data_dir is not None,
        )
        app_lease = ApplicationInstanceLease(runtime.data_dir, host=host, port=port)
        app_lease.acquire()
        writer_lease = OntologyWriterLease.shared(runtime.data_dir)
        writer_lease.acquire()
        services = build_product_services(settings, runtime_config=runtime)
        application = create_product_app(services, runtime_config=runtime)
        _warn_if_exposed(host)
        uvicorn.run(application, host=host, port=port)
    except (OperatorRuntimeError, ValueError) as error:
        _cli.typer.echo(str(error), err=True)
        raise _cli.typer.Exit(code=1) from error
    finally:
        if writer_lease is not None:
            writer_lease.release()
        if app_lease is not None:
            app_lease.release()
