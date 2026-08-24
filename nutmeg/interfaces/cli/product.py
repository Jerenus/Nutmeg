"""``nutmeg app`` — local Intelligence OS product service."""
from __future__ import annotations

import sys

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
) -> None:
    """Launch the versioned local product API (M1 headless contract)."""
    import uvicorn

    from nutmeg.interfaces.product_api import create_product_app
    from nutmeg.product.wiring import build_product_services

    settings = _cli.get_settings()
    services = build_product_services(settings)
    _warn_if_exposed(host)
    application = create_product_app(services)
    uvicorn.run(application, host=host, port=port)
