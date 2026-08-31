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
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.reliability.contracts import PERFORMANCE_BUDGETS_MS

_SHANGHAI = ZoneInfo('Asia/Shanghai')


def mount_product_ui(
    app: FastAPI,
    services,
    clock: Callable[[], datetime],
) -> None:
    """Mount local assets and ontology-backed workspace controllers."""
    web_root = Path(__file__).resolve().parent / 'web'
    templates = Jinja2Templates(directory=web_root / 'templates')
    app.mount(
        '/assets/product',
        StaticFiles(directory=web_root / 'static' / 'product'),
        name='product-assets',
    )

    @app.get('/system/command-center', include_in_schema=False)
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

    @app.get('/system/operations', include_in_schema=False)
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

    @app.get('/system/release', include_in_schema=False)
    @app.get('/release', include_in_schema=False)
    async def release_page(
        request: Request,
        release_version: Annotated[
            str | None, Query(min_length=1, max_length=100)
        ] = None,
        candidate_commit: Annotated[
            str | None, Query(min_length=1, max_length=200)
        ] = None,
        evaluated_at: Annotated[datetime | None, Query()] = None,
    ):
        cutoff = evaluated_at or clock()
        selected_version = release_version or getattr(
            services.settings, 'release_version', 'unreleased'
        )
        selected_candidate = candidate_commit or getattr(
            services.settings, 'candidate_commit', 'unresolved'
        )
        release = services.queries.release(
            release_version=selected_version,
            candidate_commit=selected_candidate,
            evaluated_at=cutoff,
        )
        return templates.TemplateResponse(
            request=request,
            name='product/release.html',
            context={
                'workspace': 'release',
                'active_nav': 'release',
                'release': release,
                'performance_budgets': PERFORMANCE_BUDGETS_MS,
                'evidence_kinds': (
                    'scheduler_authority',
                    'deterministic_suite',
                    'migration_replay',
                    'fault_matrix',
                    'ai_safety',
                    'browser_e2e',
                    'performance',
                    'backup_restore',
                    'observability',
                ),
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    @app.get('/system/tickets', include_in_schema=False)
    @app.get('/tickets', include_in_schema=False)
    async def ticket_workbench_page(
        request: Request,
        day: Annotated[date | None, Query(alias='date')] = None,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        cutoff = as_of or clock()
        selected_day = day or cutoff.astimezone(_SHANGHAI).date()
        workbench = services.queries.ticket_workbench(
            selected_day, as_of=cutoff
        )
        histories = {
            batch.ticket_batch_id: services.queries.ticket_batch(
                batch.ticket_batch_id
            )
            for batch in workbench.batch_revisions
        }
        artifacts = [
            services.queries.ticket_artifact(artifact_id, as_of=cutoff)
            for batch in workbench.batch_revisions
            for artifact_id in batch.artifact_ids
        ]
        return templates.TemplateResponse(
            request=request,
            name='product/tickets.html',
            context={
                'workspace': 'ticket-workbench',
                'active_nav': 'ticket-workbench',
                'workbench': workbench,
                'histories': histories,
                'artifacts': artifacts,
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    @app.get('/system/review', include_in_schema=False)
    @app.get('/review', include_in_schema=False)
    async def review_page(
        request: Request,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        review = services.queries.review(as_of=as_of or clock())
        return templates.TemplateResponse(
            request=request,
            name='product/review.html',
            context={
                'workspace': 'review',
                'active_nav': 'review',
                'review': review,
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    @app.get('/system/calibration', include_in_schema=False)
    @app.get('/calibration', include_in_schema=False)
    async def calibration_page(
        request: Request,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        calibration = services.queries.calibration(as_of=as_of or clock())
        return templates.TemplateResponse(
            request=request,
            name='product/calibration.html',
            context={
                'workspace': 'calibration',
                'active_nav': 'calibration',
                'calibration': calibration,
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    @app.get('/system/ontology', include_in_schema=False)
    @app.get('/ontology', include_in_schema=False)
    async def ontology_page(
        request: Request,
        object_type: Annotated[str, Query(alias='type')] = 'match',
        query: Annotated[str | None, Query(alias='q')] = None,
        after: Annotated[str | None, Query()] = None,
        object_id: Annotated[str | None, Query()] = None,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        cutoff = as_of or clock()
        page = services.queries.ontology_objects(
            object_type=object_type,
            query=query,
            after=after,
            limit=100,
            as_of=cutoff,
        )
        detail = None
        if object_id is not None:
            try:
                detail = services.queries.ontology_object(
                    object_type, object_id, as_of=cutoff
                )
            except ProductNotFoundError as error:
                return not_found_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name='product/ontology.html',
            context={
                'workspace': 'ontology',
                'active_nav': 'ontology',
                'page': page,
                'detail': detail,
                'filters': {
                    'object_type': object_type,
                    'query': query or '',
                    'as_of': cutoff.isoformat(),
                },
                'object_types': (
                    'match',
                    'team',
                    'competition',
                    'person',
                    'claim',
                    'observation',
                    'market_snapshot',
                    'forecast_revision',
                    'factor_definition',
                    'ticket',
                    'outcome',
                    'settlement',
                    'adjudication',
                    'flag_instance',
                    'prediction',
                    'action',
                ),
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    def not_found_response(request: Request, error: ProductNotFoundError):
        return templates.TemplateResponse(
            request=request,
            name='product/not_found.html',
            status_code=404,
            context={
                'workspace': 'not-found',
                'active_nav': '',
                'health': services.queries.health(),
                'alerts': [],
                'message': str(error),
            },
        )

    @app.get('/system/matches/{match_id}', include_in_schema=False)
    @app.get('/matches/{match_id}', include_in_schema=False)
    async def match_page(
        request: Request,
        match_id: str,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        try:
            detail = services.queries.match(match_id, as_of=as_of or clock())
        except ProductNotFoundError as error:
            return not_found_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name='product/match.html',
            context={
                'workspace': 'match-investigation',
                'active_nav': 'match-investigation',
                'detail': detail,
                'copilot_available': getattr(services, 'copilot', None) is not None,
                'health': services.queries.health(),
                'alerts': [],
            },
        )

    @app.get('/system/lineage/{object_type}/{object_id}', include_in_schema=False)
    @app.get('/lineage/{object_type}/{object_id}', include_in_schema=False)
    async def lineage_page(request: Request, object_type: str, object_id: str):
        try:
            lineage = services.queries.lineage(object_type, object_id)
        except ProductNotFoundError as error:
            return not_found_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name='product/lineage.html',
            context={
                'workspace': 'lineage',
                'active_nav': '',
                'lineage': lineage,
                'health': services.queries.health(),
                'alerts': [],
            },
        )
