"""Server-rendered workspaces over the versioned product contract."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.product.contracts import ReadinessLevel

_SHANGHAI = ZoneInfo('Asia/Shanghai')


def mount_product_ui(
    app: FastAPI,
    services,
    clock: Callable[[], datetime],
) -> None:
    """Mount local assets and read-only M2 workspace controllers."""
    web_root = Path(__file__).resolve().parent / 'web'
    templates = Jinja2Templates(directory=web_root / 'templates')
    app.mount(
        '/assets/product',
        StaticFiles(directory=web_root / 'static' / 'product'),
        name='product-assets',
    )

    @app.get('/', include_in_schema=False)
    async def command_center_page(
        request: Request,
        day: Annotated[date | None, Query(alias='date')] = None,
        as_of: Annotated[datetime | None, Query()] = None,
        readiness: Annotated[ReadinessLevel | None, Query()] = None,
        competition: Annotated[str | None, Query()] = None,
        query: Annotated[str | None, Query(alias='q')] = None,
    ):
        cutoff = as_of or clock()
        selected_day = day or cutoff.astimezone(_SHANGHAI).date()
        command = services.queries.command_center(
            selected_day,
            as_of=cutoff,
            readiness=readiness,
            competition=competition,
            query=query,
        )
        return templates.TemplateResponse(
            request=request,
            name='product/command_center.html',
            context={
                'workspace': 'command-center',
                'active_nav': 'command-center',
                'command': command,
                'health': command.health,
                'alerts': command.alerts,
                'filters': {
                    'date': selected_day.isoformat(),
                    'readiness': readiness.value if readiness is not None else '',
                    'competition': competition or '',
                    'query': query or '',
                },
            },
        )

    @app.get('/operations', include_in_schema=False)
    async def operations_page(
        request: Request,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        operations = services.queries.operations(as_of=as_of or clock())
        return templates.TemplateResponse(
            request=request,
            name='product/operations.html',
            context={
                'workspace': 'operations',
                'active_nav': 'operations',
                'operations': operations,
                'health': services.queries.health(),
                'alerts': operations.alerts,
            },
        )
