from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.services.client import ClientService


def _optional_alerts(service: ClientService, *, user_id: str) -> dict[str, Any]:
    alerts = getattr(service, 'alerts', None)
    if alerts is None:
        return {'alerts': []}
    return alerts(user_id=user_id)


def create_client_app(*, service: ClientService) -> FastAPI:
    app = FastAPI(title='Nutmeg AI Client')
    web_root = Path(__file__).parent / 'web'
    static_dir = web_root / 'static'
    templates = Jinja2Templates(directory=web_root / 'templates')
    manifest_path = static_dir / 'client' / 'manifest.webmanifest'
    app.mount('/static', StaticFiles(directory=static_dir), name='static')

    @app.get('/client/api/status')
    def client_status(user_id: str | None = None) -> dict[str, Any]:
        return service.status(user_id=user_id)

    @app.get('/client/manifest.webmanifest')
    def manifest() -> JSONResponse:
        return JSONResponse(json.loads(manifest_path.read_text()))

    @app.get('/client/status')
    def status_page(
        request: Request,
        user_id: str | None = None,
    ):
        payload = service.status(user_id=user_id)
        return templates.TemplateResponse(
            request,
            'client/status.html',
            {
                'title': '数据状态',
                'status': payload,
                'responsible_use': payload['responsible_use'],
            },
        )

    @app.get('/client/api/feed')
    def feed_api(
        user_id: str | None = None,
        league: str = 'epl',
        days: int = 3,
        limit: int = 5,
        demo: bool = False,
    ) -> dict[str, Any]:
        return service.daily_feed(
            user_id=user_id,
            league=league,
            days=days,
            limit=limit,
            demo=demo,
        )

    @app.get('/client')
    def feed_page(
        request: Request,
        user_id: str | None = None,
        league: str = 'epl',
        days: int = 3,
        limit: int = 5,
        demo: bool = False,
    ):
        payload = service.daily_feed(
            user_id=user_id,
            league=league,
            days=days,
            limit=limit,
            demo=demo,
        )
        return templates.TemplateResponse(
            request,
            'client/feed.html',
            {
                'title': 'Nutmeg 今日机会',
                'feed': payload,
                'opportunities': payload['opportunities'],
                'alerts': _optional_alerts(
                    service,
                    user_id=str(payload.get('user_id') or user_id or 'owner'),
                ),
                'responsible_use': payload['responsible_use'],
            },
        )

    @app.get('/client/api/matches/{fixture_id}')
    def match_api(
        fixture_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return service.match_workspace(user_id=user_id, fixture_id=fixture_id)

    @app.get('/client/matches/{fixture_id}')
    def match_page(
        request: Request,
        fixture_id: str,
        user_id: str | None = None,
    ):
        workspace = service.match_workspace(user_id=user_id, fixture_id=fixture_id)
        return templates.TemplateResponse(
            request,
            'client/match.html',
            {
                'title': '比赛分析工作台',
                'workspace': workspace,
                'alerts': _optional_alerts(
                    service,
                    user_id=str(workspace.get('user_id') or user_id or 'owner'),
                ),
                'responsible_use': workspace['responsible_use'],
            },
        )

    @app.post('/client/api/matches/{fixture_id}/questions')
    async def match_question(
        fixture_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return service.answer_question(
            user_id=body.get('user_id'),
            fixture_id=fixture_id,
            question=str(body.get('question') or ''),
        )

    @app.post('/client/api/watchlist')
    async def save_watchlist(body: dict[str, Any]) -> dict[str, Any]:
        alert_preferences = body.get('alert_preferences') or []
        if isinstance(alert_preferences, str):
            alert_preferences = [alert_preferences]
        return service.save_watchlist_item(
            user_id=str(body.get('user_id') or 'owner'),
            target_type=str(body.get('target_type') or 'fixture'),
            target_id=str(body.get('target_id') or ''),
            alert_preferences=list(alert_preferences),
        )

    @app.get('/client/api/alerts')
    def list_alerts(user_id: str) -> dict[str, Any]:
        return service.alerts(user_id=user_id)

    @app.post('/client/api/predictions')
    async def record_prediction(body: dict[str, Any]) -> dict[str, Any]:
        return service.record_prediction(
            user_id=str(body.get('user_id') or 'owner'),
            fixture_id=str(body.get('fixture_id') or ''),
            pick=str(body.get('pick') or ''),
            source_audit_id=body.get('source_audit_id'),
            client_notes=body.get('client_notes'),
        )

    return app
