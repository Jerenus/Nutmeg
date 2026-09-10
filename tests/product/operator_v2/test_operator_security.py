from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_contracts import (
    OperatorLane,
    OperatorLaneResponseV1,
    OperatorMaintenanceResponseV1,
    OperatorTaskDetailV1,
    OperatorTodayResponseV1,
)
from nutmeg.product.operator_runtime import validate_operator_runtime
from tests.product.operator_v2.test_operator_pages import (
    _OperatorQueries as _PageOperatorQueries,
)
from tests.product.operator_v2.test_operator_pages import _task, _task_detail

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
COMMIT = "b" * 40
SIGNING_KEY = "operator-security-signing-key-32-bytes"


class _NoCalls:
    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected service call: {name}")


class _OperatorQueries:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def worklist(self, *, as_of: datetime):
        return SimpleNamespace(as_of=as_of, selected=None, tasks=[])

    def today(self, *, as_of: datetime) -> OperatorTodayResponseV1:
        self.calls.append(("today", as_of))
        return OperatorTodayResponseV1(as_of=as_of, next_action=None, entries=[])

    def lane(self, lane: OperatorLane, *, as_of: datetime) -> OperatorLaneResponseV1:
        self.calls.append(("lane", lane, as_of))
        return OperatorLaneResponseV1(
            lane=lane,
            as_of=as_of,
            focus_business_key=None,
            current_tasks=[],
            archive_tasks=[],
        )

    def task_v2(self, lane: OperatorLane, business_key: str, *, as_of: datetime):
        self.calls.append(("task", lane, business_key, as_of))
        assert lane is OperatorLane.ZUCAI
        return _task_detail(_task(business_key))

    def maintenance(self, *, as_of: datetime):
        self.calls.append(("maintenance", as_of))
        return _PageOperatorQueries().maintenance(as_of=as_of)


def _client(tmp_path: Path, *, mode: str) -> tuple[TestClient, _OperatorQueries]:
    production = (tmp_path / "production").resolve()
    data_dir = (
        (tmp_path / "isolated").resolve()
        if mode == "active"
        else production
    )
    scope = "isolated_candidate" if mode == "active" else "production"
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production,
        operator_runtime_scope=scope,
        operator_surface_mode=mode,
        candidate_commit=COMMIT,
        operator_accepted_commit=COMMIT,
        operator_token_signing_key=SIGNING_KEY if mode == "active" else None,
    )
    runtime = validate_operator_runtime(
        settings,
        running_commit=COMMIT,
        dirty=False,
        data_dir_was_explicit=mode == "active",
    )
    queries = _OperatorQueries()
    services = SimpleNamespace(
        settings=settings,
        runtime=runtime,
        queries=_NoCalls(),
        actions=_NoCalls(),
        operator_queries=queries,
        operator_actions=None,
        copilot=_NoCalls(),
        tickets=_NoCalls(),
    )
    app = create_product_app(
        services,
        runtime_config=runtime,
        session_secret="operator-security-session",
        csrf_secret="operator-security-csrf",
        clock=lambda: NOW,
    )
    return TestClient(app), queries


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_v2_operator_get_routes_are_closed_and_typed(
    tmp_path: Path,
    mode: str,
) -> None:
    client, queries = _client(tmp_path, mode=mode)

    today = client.get("/api/v2/operator/today")
    lane = client.get("/api/v2/operator/lanes/zucai")
    task = client.get("/api/v2/operator/tasks/zucai/26116")
    maintenance = client.get("/api/v2/operator/maintenance")

    assert today.status_code == 200
    assert today.json()["kind"] == "operator_today_v1"
    assert lane.status_code == 200
    assert lane.json()["lane"] == "zucai"
    assert task.status_code == 200
    assert task.json()["business_key"] == "26116"
    assert maintenance.status_code == 200
    assert [call[0] for call in queries.calls] == [
        "today",
        "lane",
        "task",
        "maintenance",
    ]


def test_v2_operator_get_routes_enforce_strict_response_models(tmp_path: Path) -> None:
    client, _queries = _client(tmp_path, mode="active")
    models = {
        route.path: route.response_model
        for route in client.app.routes
        if isinstance(route, APIRoute)
    }

    assert models["/api/v2/operator/today"] is OperatorTodayResponseV1
    assert models["/api/v2/operator/lanes/{lane}"] is OperatorLaneResponseV1
    assert models["/api/v2/operator/tasks/{lane}/{business_key}"] is OperatorTaskDetailV1
    assert models["/api/v2/operator/maintenance"] is OperatorMaintenanceResponseV1


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/operator/lanes/unknown",
        "/api/v2/operator/tasks/unknown/26116",
        "/api/v2/operator/tasks/zucai/../../scoreboard.json",
    ],
)
def test_v2_operator_get_routes_reject_unknown_lane_or_path_escape(
    tmp_path: Path,
    path: str,
) -> None:
    client, queries = _client(tmp_path, mode="active")

    assert client.get(path).status_code in {404, 422}
    assert queries.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v2/operator/maintenance"),
        ("POST", "/api/v2/operator/scheduler/run"),
        ("POST", "/api/v2/operator/placement"),
        ("POST", "/api/v2/operator/scoreboard"),
        ("PUT", "/api/v2/operator/tasks/zucai/26116"),
        ("DELETE", "/api/v2/operator/tasks/zucai/26116"),
    ],
)
def test_no_guessed_scheduler_placement_or_scoreboard_mutation_route_exists(
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    client, _queries = _client(tmp_path, mode="active")

    assert client.request(method, path, content=b"not-json").status_code == 405


def test_v2_operator_reads_are_not_mounted_in_legacy_mode(tmp_path: Path) -> None:
    client, queries = _client(tmp_path, mode="legacy_read_only")

    for path in (
        "/api/v2/operator/today",
        "/api/v2/operator/lanes/jczq",
        "/api/v2/operator/tasks/zucai/26116",
        "/api/v2/operator/maintenance",
    ):
        assert client.get(path).status_code == 404
    assert queries.calls == []


def test_unavailable_operator_handler_still_enforces_the_full_command_contract(
    tmp_path: Path,
) -> None:
    client, _queries = _client(tmp_path, mode="active")
    session = client.get("/api/v1/session").json()

    response = client.post(
        "/api/v2/operator",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": session["csrf_token"],
        },
        json={
            "schema_version": "2",
            "kind": "request_settlement",
            "expected_snapshot_token": "opaque-command-token",
            "idempotency_key": "security:missing-task-key",
        },
    )

    assert response.status_code == 422
