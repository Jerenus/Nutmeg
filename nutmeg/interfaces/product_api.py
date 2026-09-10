"""Local FastAPI boundary for the versioned Nutmeg product contract."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from nutmeg.interfaces.operator_api import mount_operator_api
from nutmeg.interfaces.operator_ui import mount_operator_rollout_routes, mount_operator_ui
from nutmeg.interfaces.product_ui import mount_product_ui
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.errors import IdempotencyConflictError, OptimisticConcurrencyError
from nutmeg.product.contracts import (
    ApproveTicketBatchCommand,
    CopilotRequest,
    CreateTicketBatchCommand,
    IssueConfirmationCommand,
    ProductActionRequest,
    ProductError,
    ReadinessLevel,
    RemoveTicketLegCommand,
)
from nutmeg.product.copilot import (
    ProductCopilotResponseError,
    ProductCopilotUnavailableError,
)
from nutmeg.product.errors import (
    ProductActionBlockedError,
    ProductActionNotAllowedError,
    ProductNotFoundError,
    ProductTicketError,
)
from nutmeg.product.operator_contracts import (
    GradePredictionCommand,
    OperatorLane,
    OperatorLaneResponseV1,
    OperatorMaintenanceResponseV1,
    OperatorTaskDetailV1,
    OperatorTodayResponseV1,
    RecordDeploymentCommand,
    RequestTelegramConfirmationCommand,
    ResolveIssueAdjudicationCommand,
    SelectTicketVersionCommand,
)
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.reliability.metrics import RouteMetricsRegistry

_SESSION_COOKIE = 'nutmeg_session'


def create_product_app(
    services,
    session_secret: str | None = None,
    csrf_secret: str | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    runtime_config: OperatorRuntimeConfig | None = None,
) -> FastAPI:
    """Create one process-local, single-user application boundary."""
    now = clock or (lambda: datetime.now(UTC))
    session_key = (session_secret or secrets.token_urlsafe(32)).encode()
    csrf_key = (csrf_secret or secrets.token_urlsafe(32)).encode()
    session_token = hmac.new(
        session_key, b'nutmeg-local-session', hashlib.sha256
    ).hexdigest()
    csrf_token = hmac.new(csrf_key, session_token.encode(), hashlib.sha256).hexdigest()
    runtime = runtime_config or getattr(services, 'runtime', None)
    if runtime is None:
        data_dir = services.settings.data_dir.resolve()
        runtime = OperatorRuntimeConfig(
            surface_mode=OperatorSurfaceMode.LEGACY_READ_ONLY,
            runtime_scope=OperatorRuntimeScope.PRODUCTION,
            data_dir=data_dir,
            production_data_dir=data_dir,
            running_commit='unresolved',
        )

    infrastructure_workers = getattr(services, 'infrastructure_workers', None)
    app = FastAPI(
        title='Nutmeg Intelligence OS',
        version='1',
        lifespan=(
            None
            if infrastructure_workers is None
            else infrastructure_workers.lifespan
        ),
    )
    route_metrics = RouteMetricsRegistry()

    mount_operator_rollout_routes(app, runtime)

    @app.middleware('http')
    async def guard_retired_mutations(request: Request, call_next):
        if request.method in {
            'POST',
            'PUT',
            'PATCH',
            'DELETE',
        }:
            path = request.url.path
            legacy_write = (
                path == '/api/v1/actions'
                or path == '/api/v1/ticket-batches'
                or path.startswith('/api/v1/ticket-batches/')
                or path.startswith('/api/v1/ticket-artifacts/')
                or (
                    path.startswith('/api/v1/operator/tasks/')
                    and path.rsplit('/', 1)[-1]
                    in {
                        'adjudications',
                        'candidate',
                        'deployment',
                        'telegram-confirmation',
                        'grade-prediction',
                    }
                )
                or (path.startswith('/api/v1/matches/') and path.endswith('/copilot'))
            )
            v2_write = path.startswith('/api/v2/')
            exact_v2_allowed = (
                path == '/api/v2/operator'
                and request.method == 'POST'
                and runtime.surface_mode is OperatorSurfaceMode.ACTIVE
            )
            if legacy_write or (v2_write and not exact_v2_allowed):
                return JSONResponse(
                    status_code=405,
                    content={
                        'code': 'method_not_allowed',
                        'message': 'this mutation route is not available',
                    },
                )
        return await call_next(request)

    @app.middleware('http')
    async def observe_allowlisted_route(request: Request, call_next):
        started_ns = time.perf_counter_ns()
        status_code = 500
        failed = False
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            failed = True
            raise
        finally:
            route = request.scope.get('route')
            route_template = getattr(route, 'path', None)
            if isinstance(route_template, str):
                route_metrics.record(
                    method=request.method,
                    route_template=route_template,
                    duration_ns=time.perf_counter_ns() - started_ns,
                    status_code=status_code,
                    failed=failed,
                )

    def error_response(status_code: int, error: ProductError) -> JSONResponse:
        return JSONResponse(status_code=status_code, content=error.model_dump(mode='json'))

    @app.exception_handler(ProductNotFoundError)
    async def product_not_found(_request: Request, error: ProductNotFoundError):
        return error_response(
            404, ProductError(code='object_not_found', message=str(error))
        )

    @app.exception_handler(ProductActionNotAllowedError)
    async def action_not_allowed(_request: Request, error: ProductActionNotAllowedError):
        return error_response(
            403, ProductError(code='action_not_allowed', message=str(error))
        )

    @app.exception_handler(ProductActionBlockedError)
    async def action_blocked(_request: Request, error: ProductActionBlockedError):
        return error_response(409, ProductError(code='action_blocked', message=str(error)))

    @app.exception_handler(ProductTicketError)
    async def ticket_error(_request: Request, error: ProductTicketError):
        return error_response(
            error.status_code,
            ProductError(
                code=error.code,
                message=str(error),
                retryable=error.retryable,
            ),
        )

    @app.exception_handler(ProductCopilotUnavailableError)
    async def copilot_unavailable(
        _request: Request, _error: ProductCopilotUnavailableError
    ):
        return error_response(
            503,
            ProductError(
                code='copilot_unavailable',
                message='copilot provider is unavailable',
                retryable=True,
            ),
        )

    @app.exception_handler(ProductCopilotResponseError)
    async def copilot_response_invalid(
        _request: Request, _error: ProductCopilotResponseError
    ):
        return error_response(
            422,
            ProductError(
                code='copilot_response_invalid',
                message='copilot returned an invalid investigation draft',
            ),
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(_request: Request, error: IdempotencyConflictError):
        return error_response(
            409, ProductError(code='idempotency_conflict', message=str(error))
        )

    @app.exception_handler(OptimisticConcurrencyError)
    async def optimistic_conflict(_request: Request, error: OptimisticConcurrencyError):
        return error_response(
            409, ProductError(code='version_conflict', message=str(error), retryable=False)
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, error: RequestValidationError):
        if request.url.path.endswith('/confirm') and any(
            'receipt_base64' in item['loc'] or 'receipt_content_type' in item['loc']
            for item in error.errors()
        ):
            return error_response(
                422,
                ProductError(
                    code='receipt_required',
                    message='manual receipt and content type are required',
                ),
            )
        field_errors: dict[str, list[str]] = {}
        for item in error.errors():
            field = '.'.join(str(part) for part in item['loc'] if part != 'body') or 'body'
            field_errors.setdefault(field, []).append(item['msg'])
        return error_response(
            422,
            ProductError(
                code='validation_error',
                message='request validation failed',
                field_errors=field_errors,
            ),
        )

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, error: ValueError):
        return error_response(422, ProductError(code='validation_error', message=str(error)))

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        return error_response(
            error.status_code,
            ProductError(code='request_forbidden', message=str(error.detail)),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        correlation_id = f'err-{uuid4().hex}'
        return error_response(
            500,
            ProductError(
                code='internal_error',
                message='internal server error',
                details={'correlation_id': correlation_id},
            ),
        )

    async def require_mutation_session(request: Request) -> None:
        cookie = request.cookies.get(_SESSION_COOKIE)
        supplied_csrf = request.headers.get('X-CSRF-Token')
        origin = request.headers.get('Origin')
        expected_origin = f'{request.url.scheme}://{request.url.netloc}'
        if cookie is None or not hmac.compare_digest(cookie, session_token):
            raise HTTPException(status_code=403, detail='local session is required')
        if supplied_csrf is None or not hmac.compare_digest(supplied_csrf, csrf_token):
            raise HTTPException(status_code=403, detail='valid CSRF token is required')
        if origin != expected_origin:
            raise HTTPException(status_code=403, detail='same-origin request is required')

    if runtime.surface_mode is OperatorSurfaceMode.ACTIVE:
        mount_operator_api(
            app,
            require_mutation_session=require_mutation_session,
            operator_actions=services.operator_actions,
            actor_id=services.settings.default_user_id,
        )

    if runtime.surface_mode is not OperatorSurfaceMode.LEGACY_READ_ONLY:

        @app.get('/api/v2/operator/today', response_model=OperatorTodayResponseV1)
        async def operator_today_v2(
            as_of: Annotated[datetime | None, Query()] = None,
        ):
            return services.operator_queries.today(as_of=as_of or now())

        @app.get(
            '/api/v2/operator/lanes/{lane}',
            response_model=OperatorLaneResponseV1,
        )
        async def operator_lane_v2(
            lane: OperatorLane,
            as_of: Annotated[datetime | None, Query()] = None,
        ):
            return services.operator_queries.lane(lane, as_of=as_of or now())

        @app.get(
            '/api/v2/operator/tasks/{lane}/{business_key}',
            response_model=OperatorTaskDetailV1,
        )
        async def operator_task_v2(
            lane: OperatorLane,
            business_key: str,
            as_of: Annotated[datetime | None, Query()] = None,
        ):
            return services.operator_queries.task_v2(
                lane,
                business_key,
                as_of=as_of or now(),
            )

        @app.get(
            '/api/v2/operator/maintenance',
            response_model=OperatorMaintenanceResponseV1,
        )
        async def operator_maintenance_v2(
            as_of: Annotated[datetime | None, Query()] = None,
        ):
            return services.operator_queries.maintenance(as_of=as_of or now())

    @app.get('/api/v1/session')
    async def session() -> JSONResponse:
        response = JSONResponse({'csrf_token': csrf_token})
        response.set_cookie(
            _SESSION_COOKIE,
            session_token,
            httponly=True,
            samesite='strict',
            secure=False,
            path='/',
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/v1/system/health')
    async def health():
        return services.queries.health()

    @app.get('/api/v1/board')
    async def board(
        day: Annotated[date, Query(alias='date')],
        as_of: Annotated[datetime | None, Query()] = None,
        readiness: Annotated[ReadinessLevel | None, Query()] = None,
        competition: Annotated[str | None, Query()] = None,
        query: Annotated[str | None, Query(alias='q')] = None,
    ):
        return services.queries.command_center(
            day,
            as_of=as_of or now(),
            readiness=readiness,
            competition=competition,
            query=query,
        ).board

    @app.get('/api/v1/command-center')
    async def command_center(
        day: Annotated[date, Query(alias='date')],
        as_of: Annotated[datetime | None, Query()] = None,
        readiness: Annotated[ReadinessLevel | None, Query()] = None,
        competition: Annotated[str | None, Query()] = None,
        query: Annotated[str | None, Query(alias='q')] = None,
    ):
        return services.queries.command_center(
            day,
            as_of=as_of or now(),
            readiness=readiness,
            competition=competition,
            query=query,
        )

    @app.get('/api/v1/operations')
    async def operations(as_of: Annotated[datetime | None, Query()] = None):
        return services.queries.operations(as_of=as_of or now())

    @app.get('/api/v1/operator/tasks')
    async def operator_tasks(
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.operator_queries.worklist(as_of=as_of or now())

    @app.get('/api/v1/operator/tasks/{task_id}')
    async def operator_task(
        task_id: str,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.operator_queries.task(task_id, as_of=as_of or now())

    @app.post('/api/v1/operator/tasks/{task_id}/adjudications')
    async def resolve_operator_adjudication(
        task_id: str,
        command: ResolveIssueAdjudicationCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return services.operator_actions.resolve_issue_adjudication(
            task_id,
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    @app.post('/api/v1/operator/tasks/{task_id}/candidate')
    async def select_operator_candidate(
        task_id: str,
        command: SelectTicketVersionCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return services.operator_actions.select_ticket_version(
            task_id,
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    @app.post('/api/v1/operator/tasks/{task_id}/deployment')
    async def record_operator_deployment(
        task_id: str,
        command: RecordDeploymentCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return services.operator_actions.record_deployment(
            task_id,
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    @app.post('/api/v1/operator/tasks/{task_id}/telegram-confirmation')
    async def request_operator_telegram_confirmation(
        task_id: str,
        command: RequestTelegramConfirmationCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return services.operator_actions.request_telegram_confirmation(
            task_id,
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    @app.post('/api/v1/operator/tasks/{task_id}/grade-prediction')
    async def grade_operator_prediction(
        task_id: str,
        command: GradePredictionCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return services.operator_actions.grade_prediction(
            task_id,
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    @app.get('/api/v1/release')
    async def release(
        release_version: Annotated[str, Query(min_length=1, max_length=100)],
        candidate_commit: Annotated[str, Query(min_length=1, max_length=200)],
        evaluated_at: Annotated[datetime, Query()],
    ):
        return services.queries.release(
            release_version=release_version,
            candidate_commit=candidate_commit,
            evaluated_at=evaluated_at,
        )

    @app.get('/api/v1/reliability/metrics')
    async def reliability_metrics(
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.queries.reliability_metrics(
            as_of=as_of or now(), routes=route_metrics.snapshot()
        )

    @app.get('/api/v1/review')
    async def review(as_of: Annotated[datetime | None, Query()] = None):
        return services.queries.review(as_of=as_of or now())

    @app.get('/api/v1/calibration')
    async def calibration(as_of: Annotated[datetime | None, Query()] = None):
        return services.queries.calibration(as_of=as_of or now())

    @app.get('/api/v1/ontology/objects')
    async def ontology_objects(
        object_type: Annotated[str, Query(alias='type')],
        query: Annotated[str | None, Query(alias='q', max_length=200)] = None,
        after: Annotated[str | None, Query(max_length=2000)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.queries.ontology_objects(
            object_type=object_type,
            query=query,
            after=after,
            limit=limit,
            as_of=as_of or now(),
        )

    @app.get('/api/v1/ontology/objects/{object_type}/{object_id}')
    async def ontology_object(
        object_type: str,
        object_id: str,
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.queries.ontology_object(
            object_type, object_id, as_of=as_of or now()
        )

    @app.get('/api/v1/scoreboard')
    async def scoreboard(as_of: Annotated[datetime | None, Query()] = None):
        return services.queries.scoreboard(as_of=as_of or now())

    @app.get('/api/v1/alerts')
    async def alerts(as_of: Annotated[datetime | None, Query()] = None):
        return services.queries.operations(as_of=as_of or now()).alerts

    @app.get('/api/v1/identities')
    async def identities(
        as_of: Annotated[datetime | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        return services.queries.operations(
            as_of=as_of or now(), identity_limit=limit
        ).identities

    @app.get('/api/v1/matches/{match_id}')
    async def match(
        match_id: str, as_of: Annotated[datetime | None, Query()] = None
    ):
        return services.queries.match(match_id, as_of=as_of or now())

    @app.get('/api/v1/ticket-workbench')
    async def ticket_workbench(
        day: Annotated[date, Query(alias='date')],
        as_of: Annotated[datetime | None, Query()] = None,
    ):
        return services.queries.ticket_workbench(day, as_of=as_of or now())

    @app.get('/api/v1/ticket-batches/{ticket_batch_id}')
    async def ticket_batch(ticket_batch_id: str):
        return services.queries.ticket_batch(ticket_batch_id)

    @app.get('/api/v1/ticket-artifacts/{ticket_artifact_id}')
    async def ticket_artifact(ticket_artifact_id: str):
        return services.queries.ticket_artifact(ticket_artifact_id, as_of=now())

    def ticket_action_response(response):
        if response.status == 'rejected':
            return error_response(
                403,
                ProductError(
                    code=response.error_code or 'action_rejected',
                    message=response.error_detail or 'action was rejected',
                    action_id=response.action_id,
                ),
            )
        return response

    @app.post('/api/v1/ticket-batches')
    async def create_ticket_batch(
        command: CreateTicketBatchCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return ticket_action_response(services.tickets.create_batch(command))

    @app.post('/api/v1/ticket-batches/{ticket_batch_id}/remove-leg')
    async def remove_ticket_leg(
        ticket_batch_id: str,
        command: RemoveTicketLegCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return ticket_action_response(
            services.tickets.remove_leg(ticket_batch_id, command)
        )

    @app.post('/api/v1/ticket-batches/{ticket_batch_id}/approve')
    async def approve_ticket_batch(
        ticket_batch_id: str,
        command: ApproveTicketBatchCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return ticket_action_response(
            services.tickets.approve_batch(ticket_batch_id, command)
        )

    @app.post('/api/v1/ticket-artifacts/{ticket_artifact_id}/confirmations')
    async def issue_ticket_confirmation(
        ticket_artifact_id: str,
        command: IssueConfirmationCommand,
        _session: None = Depends(require_mutation_session),
    ):
        return ticket_action_response(
            services.tickets.issue_confirmation(ticket_artifact_id, command)
        )

    @app.get('/api/v1/lineage/{object_type}/{object_id}')
    async def lineage(object_type: str, object_id: str):
        return services.queries.lineage(object_type, object_id)

    @app.get('/api/v1/actions')
    async def actions(
        after: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        return services.queries.actions(after=after, limit=limit)

    @app.post('/api/v1/actions')
    async def execute_action(
        command: ProductActionRequest,
        _session: None = Depends(require_mutation_session),
    ):
        response = services.actions.execute(
            command,
            actor_id=services.settings.default_user_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
        )
        if response.status == 'rejected':
            return error_response(
                403,
                ProductError(
                    code=response.error_code or 'action_rejected',
                    message=response.error_detail or 'action was rejected',
                    action_id=response.action_id,
                ),
            )
        return response

    @app.post('/api/v1/matches/{match_id}/copilot')
    async def investigate_match(
        match_id: str,
        command: CopilotRequest,
        _session: None = Depends(require_mutation_session),
    ):
        if services.copilot is None:
            raise ProductCopilotUnavailableError('copilot is disabled')
        return services.copilot.investigate(
            match_id,
            prompt=command.prompt,
            as_of=command.as_of,
            idempotency_key=command.idempotency_key,
        )

    @app.get('/api/v1/events')
    async def events(
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        return services.queries.events(after=after, limit=limit)

    @app.get('/api/v1/events/stream')
    async def event_stream(
        after: Annotated[int, Query(ge=0)] = 0,
        once: Annotated[bool, Query()] = False,
    ):
        async def generate():
            cursor = after
            last_activity = time.monotonic()
            while True:
                page = services.queries.events(after=cursor, limit=100)
                projection_signals = getattr(services, "projection_signals", None)
                items = page.items
                if projection_signals is not None:
                    delivered = projection_signals.delivered_sequence
                    items = [
                        event for event in items if event.sequence <= delivered
                    ]
                if items:
                    for event in items:
                        payload = canonical_json(event.model_dump(mode='json'))
                        yield (
                            f'id: {event.sequence}\n'
                            f'event: {event.topic}\n'
                            f'data: {payload}\n\n'
                        )
                        cursor = event.sequence
                    last_activity = time.monotonic()
                if once:
                    return
                if time.monotonic() - last_activity >= 15:
                    yield ': heartbeat\n\n'
                    last_activity = time.monotonic()
                if projection_signals is None:
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.to_thread(
                        projection_signals.wait_for_delivery,
                        after=cursor,
                        timeout_seconds=0.5,
                    )

        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    mount_operator_ui(
        app,
        services,
        now,
        mount_root=runtime.runtime_scope is OperatorRuntimeScope.PRODUCTION,
        mount_next=(
            runtime.surface_mode is OperatorSurfaceMode.SHADOW
            or (
                runtime.runtime_scope is OperatorRuntimeScope.ISOLATED_CANDIDATE
                and runtime.surface_mode is OperatorSurfaceMode.ACTIVE
            )
        ),
        read_only=runtime.surface_mode is not OperatorSurfaceMode.ACTIVE,
    )
    mount_product_ui(app, services, now)
    return app
