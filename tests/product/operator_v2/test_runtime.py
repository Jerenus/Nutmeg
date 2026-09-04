from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_runtime import (
    ApplicationInstanceLease,
    OntologyWriterLease,
    OperatorRuntimeError,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
    SourceIdentity,
    probe_source_identity,
    validate_operator_runtime,
)

COMMIT = "a" * 40
SIGNING_KEY = "isolated-operator-signing-key-32-bytes"


def _settings(tmp_path: Path, **updates: object) -> AppSettings:
    production = tmp_path / "production"
    values: dict[str, object] = {
        "data_dir": production,
        "production_data_dir": production,
        "_env_file": None,
    }
    values.update(updates)
    return AppSettings(**values)


def test_operator_runtime_defaults_are_read_only_production(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert settings.operator_surface_mode is OperatorSurfaceMode.LEGACY_READ_ONLY
    assert settings.operator_runtime_scope is OperatorRuntimeScope.PRODUCTION
    assert settings.telegram_update_owner == "openclaw"
    assert settings.operator_scheduler_enabled is False


@pytest.mark.parametrize(
    ("scope", "mode"),
    [
        ("production", "legacy_read_only"),
        ("production", "shadow"),
        ("production", "active"),
        ("isolated_candidate", "active"),
    ],
)
def test_only_four_runtime_pairs_are_legal(
    tmp_path: Path, scope: str, mode: str
) -> None:
    production = tmp_path / "production"
    isolated = tmp_path / "isolated"
    active = mode == "active"
    settings = _settings(
        tmp_path,
        data_dir=isolated if scope == "isolated_candidate" else production,
        operator_runtime_scope=scope,
        operator_surface_mode=mode,
        candidate_commit=COMMIT,
        operator_accepted_commit=COMMIT,
        operator_token_signing_key=SIGNING_KEY if active else None,
    )

    runtime = validate_operator_runtime(
        settings,
        running_commit=COMMIT,
        dirty=False,
        data_dir_was_explicit=scope == "isolated_candidate",
    )

    assert runtime.runtime_scope.value == scope
    assert runtime.surface_mode.value == mode


@pytest.mark.parametrize(
    ("scope", "mode"),
    [
        ("isolated_candidate", "legacy_read_only"),
        ("isolated_candidate", "shadow"),
    ],
)
def test_other_runtime_pairs_are_rejected(
    tmp_path: Path, scope: str, mode: str
) -> None:
    settings = _settings(
        tmp_path,
        data_dir=tmp_path / "isolated",
        operator_runtime_scope=scope,
        operator_surface_mode=mode,
    )

    with pytest.raises(ValueError, match="illegal operator runtime scope/mode"):
        validate_operator_runtime(
            settings,
            running_commit=COMMIT,
            dirty=False,
            data_dir_was_explicit=True,
        )


@pytest.mark.parametrize("field", ["operator_surface_mode", "operator_runtime_scope"])
def test_runtime_enums_reject_unknown_values(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, **{field: "unknown"})


def test_production_scope_requires_exact_resolved_data_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path, data_dir=tmp_path / "other")

    with pytest.raises(ValueError, match="production data directory"):
        validate_operator_runtime(settings, running_commit=COMMIT, dirty=False)


@pytest.mark.parametrize(
    ("data_dir", "explicit", "message"),
    [
        (Path("relative-candidate"), True, "absolute"),
        (Path("isolated"), False, "explicit --data-dir"),
    ],
)
def test_isolated_candidate_requires_explicit_absolute_cli_path(
    tmp_path: Path, data_dir: Path, explicit: bool, message: str
) -> None:
    settings = _settings(
        tmp_path,
        data_dir=data_dir if not data_dir.is_absolute() else data_dir,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key=SIGNING_KEY,
    )

    with pytest.raises(ValueError, match=message):
        validate_operator_runtime(
            settings,
            running_commit=COMMIT,
            dirty=True,
            data_dir_was_explicit=explicit,
        )


def test_isolated_active_rejects_production_path_before_side_effects(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key=SIGNING_KEY,
        telegram_bot_token="secret",
    )

    with pytest.raises(ValueError, match="isolated candidate data directory"):
        validate_operator_runtime(
            settings,
            running_commit=COMMIT,
            dirty=True,
            data_dir_was_explicit=True,
        )


@pytest.mark.parametrize(
    "side_effect",
    [
        {"telegram_bot_token": "secret"},
        {"operator_scheduler_enabled": True},
    ],
)
def test_isolated_active_rejects_real_side_effect_configuration(
    tmp_path: Path, side_effect: dict[str, object]
) -> None:
    settings = _settings(
        tmp_path,
        data_dir=(tmp_path / "isolated").resolve(),
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key=SIGNING_KEY,
        **side_effect,
    )

    with pytest.raises(ValueError, match="side effects"):
        validate_operator_runtime(
            settings,
            running_commit=COMMIT,
            dirty=True,
            data_dir_was_explicit=True,
        )


@pytest.mark.parametrize(
    ("accepted", "candidate", "running", "dirty"),
    [
        ("b" * 40, COMMIT, COMMIT, False),
        (COMMIT, "short", COMMIT, False),
        (COMMIT, COMMIT, "unresolved", False),
        (COMMIT, COMMIT, COMMIT, True),
        ("", "", "", False),
    ],
)
def test_production_active_requires_three_identical_clean_full_commits(
    tmp_path: Path,
    accepted: str,
    candidate: str,
    running: str,
    dirty: bool,
) -> None:
    settings = _settings(
        tmp_path,
        operator_surface_mode="active",
        candidate_commit=candidate,
        operator_accepted_commit=accepted,
        operator_token_signing_key=SIGNING_KEY,
    )

    with pytest.raises(ValueError, match="accepted.*candidate.*running"):
        validate_operator_runtime(settings, running_commit=running, dirty=dirty)


@pytest.mark.parametrize("key", [None, "short", "x" * 31])
def test_active_runtime_requires_independent_32_byte_signing_key(
    tmp_path: Path, key: str | None
) -> None:
    settings = _settings(
        tmp_path,
        operator_surface_mode="active",
        candidate_commit=COMMIT,
        operator_accepted_commit=COMMIT,
        operator_token_signing_key=key,
    )

    with pytest.raises(ValueError, match="signing key"):
        validate_operator_runtime(settings, running_commit=COMMIT, dirty=False)


def test_isolated_active_accepts_an_identifiable_dirty_checkout(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        data_dir=(tmp_path / "isolated").resolve(),
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key=SIGNING_KEY,
    )

    runtime = validate_operator_runtime(
        settings,
        running_commit=COMMIT,
        dirty=True,
        data_dir_was_explicit=True,
    )

    assert runtime.runtime_scope is OperatorRuntimeScope.ISOLATED_CANDIDATE


class _Runner:
    def __init__(self, responses: list[SimpleNamespace | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append((argv, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _completed(stdout: bytes, *, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


def test_source_identity_probe_uses_two_fixed_non_shell_commands(tmp_path: Path) -> None:
    runner = _Runner([_completed((COMMIT + "\n").encode()), _completed(b"")])

    identity = probe_source_identity(tmp_path, runner=runner)

    assert identity == SourceIdentity(running_commit=COMMIT, dirty=False, resolved=True)
    assert [call[0] for call in runner.calls] == [
        ["git", "-C", str(tmp_path.resolve()), "rev-parse", "--verify", "HEAD"],
        [
            "git",
            "-C",
            str(tmp_path.resolve()),
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
        ],
    ]
    assert all(call[1]["shell"] is False for call in runner.calls)
    assert all(call[1]["timeout"] == 5 for call in runner.calls)


@pytest.mark.parametrize(
    "responses",
    [
        [_completed(b"short\n"), _completed(b"")],
        [_completed((COMMIT + "\n").encode(), returncode=1)],
        [_completed((COMMIT + "\n").encode()), _completed("dirty-\N{SNOWMAN}".encode())],
        [_completed((COMMIT + "\n").encode()), _completed(b"x" * 65_537)],
        [subprocess.TimeoutExpired("git", 5)],
    ],
)
def test_source_identity_probe_fails_closed(
    tmp_path: Path, responses: list[SimpleNamespace | BaseException]
) -> None:
    identity = probe_source_identity(tmp_path, runner=_Runner(responses))

    assert identity.resolved is False
    assert identity.running_commit == "unresolved"


def _child_app_lease(data_dir: Path) -> subprocess.Popen[str]:
    script = """
import sys
from pathlib import Path
from nutmeg.product.operator_runtime import ApplicationInstanceLease
lease = ApplicationInstanceLease(Path(sys.argv[1]), host='127.0.0.1', port=9876)
lease.acquire()
print('READY', flush=True)
sys.stdin.readline()
lease.release()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    return process


def test_application_lease_detects_real_process_contention(tmp_path: Path) -> None:
    process = _child_app_lease(tmp_path / "data")
    try:
        with pytest.raises(OperatorRuntimeError) as caught:
            ApplicationInstanceLease(
                tmp_path / "data", host="127.0.0.1", port=9877
            ).acquire()
        assert caught.value.code == "app_instance_conflict"
    finally:
        assert process.stdin is not None
        process.stdin.write("\n")
        process.stdin.flush()
        process.wait(timeout=5)


def test_application_lease_reclaims_dead_process_record(tmp_path: Path) -> None:
    process = _child_app_lease(tmp_path / "data")
    process.kill()
    process.wait(timeout=5)

    lease = ApplicationInstanceLease(tmp_path / "data", host="127.0.0.1", port=9877)
    lease.acquire()
    try:
        record = json.loads((tmp_path / "data/state/operator-app.lock").read_text())
        assert record["pid"] == os.getpid()
        assert record["bind"] == "127.0.0.1"
        assert record["port"] == 9877
    finally:
        lease.release()


def test_clean_release_keeps_stable_inode_and_allows_same_pid_restart(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    first = ApplicationInstanceLease(data_dir, host="127.0.0.1", port=9876)
    first.acquire()
    inode = first.path.stat().st_ino

    first.release()

    assert first.path.stat().st_ino == inode
    released = json.loads(first.path.read_text())
    assert released["lease_state"] == "released"

    second = ApplicationInstanceLease(data_dir, host="127.0.0.1", port=9877)
    second.acquire()
    try:
        assert second.path.stat().st_ino == inode
        held = json.loads(second.path.read_text())
        assert held["lease_state"] == "held"
        assert held["port"] == 9877
    finally:
        second.release()


@pytest.mark.parametrize("content", ["", "{}", "not-json"])
def test_existing_unverifiable_app_lock_fails_closed(
    tmp_path: Path, content: str
) -> None:
    lock = tmp_path / "data/state/operator-app.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(content)

    with pytest.raises(OperatorRuntimeError) as caught:
        ApplicationInstanceLease(
            tmp_path / "data", host="127.0.0.1", port=9877
        ).acquire()

    assert caught.value.code == "app_instance_conflict"


def test_isolated_data_directory_has_an_independent_app_lease(tmp_path: Path) -> None:
    first = ApplicationInstanceLease(
        tmp_path / "one", host="127.0.0.1", port=9876
    )
    second = ApplicationInstanceLease(
        tmp_path / "two", host="127.0.0.1", port=9877
    )
    first.acquire()
    second.acquire()
    second.release()
    first.release()


def test_writer_shared_leases_are_compatible_and_exclusive_is_guarded(
    tmp_path: Path,
) -> None:
    first = OntologyWriterLease.shared(tmp_path / "data")
    second = OntologyWriterLease.shared(tmp_path / "data")
    exclusive = OntologyWriterLease.exclusive(tmp_path / "data")
    first.acquire()
    second.acquire()
    try:
        with pytest.raises(OperatorRuntimeError) as caught:
            exclusive.acquire()
        assert caught.value.code == "ontology_maintenance_conflict"
    finally:
        second.release()
        first.release()

    exclusive.acquire()
    exclusive.release()


class _NoCalls:
    def __getattr__(self, name: str):
        raise AssertionError(f"read-only shell called {name}")


class _EmptyOperatorQueries:
    def worklist(self, *, as_of: datetime):
        return SimpleNamespace(as_of=as_of, selected=None, tasks=[])


def _runtime_app(tmp_path: Path, *, scope: str, mode: str) -> TestClient:
    production = (tmp_path / "production").resolve()
    data_dir = (
        (tmp_path / "isolated").resolve()
        if scope == "isolated_candidate"
        else production
    )
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
        data_dir_was_explicit=scope == "isolated_candidate",
    )
    services = SimpleNamespace(
        settings=settings,
        runtime=runtime,
        queries=_NoCalls(),
        actions=_NoCalls(),
        operator_queries=_EmptyOperatorQueries(),
        operator_actions=None,
        copilot=_NoCalls(),
        tickets=_NoCalls(),
    )
    return TestClient(
        create_product_app(
            services,
            runtime_config=runtime,
            session_secret="runtime-session",
            csrf_secret="runtime-csrf",
            clock=lambda: datetime(2026, 9, 4, 8, tzinfo=UTC),
        )
    )


@pytest.mark.parametrize(
    ("scope", "mode", "root_status", "next_status", "legacy_status", "v2_status"),
    [
        ("production", "legacy_read_only", 200, 404, 405, 405),
        ("production", "shadow", 200, 200, 405, 405),
        ("isolated_candidate", "active", 307, 200, 405, 422),
        ("production", "active", 200, 307, 405, 422),
    ],
)
def test_operator_route_matrix(
    tmp_path: Path,
    scope: str,
    mode: str,
    root_status: int,
    next_status: int,
    legacy_status: int,
    v2_status: int,
) -> None:
    client = _runtime_app(tmp_path, scope=scope, mode=mode)
    assert client.get("/", follow_redirects=False).status_code == root_status
    assert client.get("/operator-next", follow_redirects=False).status_code == next_status
    assert client.post("/api/v1/actions", content=b"not-json").status_code == legacy_status
    assert client.post("/api/v2/operator", json={}).status_code == v2_status


def test_active_runtime_registers_exactly_one_operator_command_route(
    tmp_path: Path,
) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")

    command_routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", None) == "/api/v2/operator"
        and "POST" in (getattr(route, "methods", None) or set())
    ]

    assert len(command_routes) == 1


def test_active_runtime_does_not_register_a_web_placement_route(
    tmp_path: Path,
) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")

    placement_routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", None)
        in {
            "/api/v1/ticket-artifacts/{ticket_artifact_id}/confirm",
            "/api/v2/operator/ticket-artifacts/{ticket_artifact_id}/confirm",
        }
        and "POST" in (getattr(route, "methods", None) or set())
    ]

    assert placement_routes == []


LEGACY_WRITE_PATHS = (
    "/api/v1/operator/tasks/zucai:26112/adjudications",
    "/api/v1/operator/tasks/zucai:26112/candidate",
    "/api/v1/operator/tasks/zucai:26112/deployment",
    "/api/v1/operator/tasks/zucai:26112/telegram-confirmation",
    "/api/v1/operator/tasks/zucai:26112/grade-prediction",
    "/api/v1/ticket-batches",
    "/api/v1/ticket-batches/batch/remove-leg",
    "/api/v1/ticket-batches/batch/approve",
    "/api/v1/ticket-artifacts/artifact/confirmations",
    "/api/v1/ticket-artifacts/artifact/confirm",
    "/api/v1/actions",
    "/api/v1/matches/match/copilot",
)


@pytest.mark.parametrize("path", LEGACY_WRITE_PATHS)
def test_every_legacy_write_is_405_before_body_parsing(
    tmp_path: Path, path: str
) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")

    response = client.post(
        path,
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 405
    assert "this is not json" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v2/other"),
        ("PUT", "/api/v2/operator"),
        ("PATCH", "/api/v2/operator/guessed"),
        ("DELETE", "/api/v2/operator/guessed"),
    ],
)
def test_guessed_v2_mutations_are_405(
    tmp_path: Path, method: str, path: str
) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")

    assert client.request(method, path, content=b"not-json").status_code == 405


def test_shadow_candidate_renders_the_read_only_workbench(tmp_path: Path) -> None:
    client = _runtime_app(tmp_path, scope="production", mode="shadow")

    response = client.get("/operator-next")

    assert response.status_code == 200
    assert 'data-workspace="operator-tasks"' in response.text
    assert 'data-read-only="true"' in response.text
    assert "当前没有待处理任务" in response.text
    assert "<form" not in response.text
    assert "{" not in response.text


def test_legacy_root_preserves_the_existing_task_view_without_forms(tmp_path: Path) -> None:
    client = _runtime_app(tmp_path, scope="production", mode="legacy_read_only")

    response = client.get("/")

    assert response.status_code == 200
    assert 'data-empty-state="operator-tasks"' in response.text
    assert "<form" not in response.text
    assert 'data-read-only="true"' in response.text


def test_active_v2_known_but_uninstalled_command_fails_closed(tmp_path: Path) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")
    session = client.get("/api/v1/session")
    token = "opaque-snapshot-token"

    response = client.post(
        "/api/v2/operator",
        headers={
            "X-CSRF-Token": session.json()["csrf_token"],
            "Origin": "http://testserver",
        },
        json={
            "schema_version": "2",
            "kind": "freeze_evidence",
            "expected_snapshot_token": token,
            "idempotency_key": "runtime:unavailable:1",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "command_unavailable"
    assert token not in response.text


def test_active_v2_base_envelope_rejects_unknown_and_extra_fields(tmp_path: Path) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")

    unknown = client.post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "automatic_bet",
            "expected_snapshot_token": "opaque",
            "idempotency_key": "runtime:unknown:1",
        },
    )
    extra = client.post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "freeze_evidence",
            "expected_snapshot_token": "opaque",
            "idempotency_key": "runtime:extra:1",
            "actor_role": "ai_analyst",
        },
    )

    assert unknown.status_code == 422
    assert extra.status_code == 422


def test_active_v2_command_envelope_is_closed_and_unavailable_without_handler(
    tmp_path: Path,
) -> None:
    client = _runtime_app(tmp_path, scope="isolated_candidate", mode="active")
    command = {
        "schema_version": "2",
        "kind": "freeze_evidence",
        "expected_snapshot_token": "opaque-snapshot-token",
        "idempotency_key": "browser:test:freeze",
    }
    session = client.get("/api/v1/session")
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": session.json()["csrf_token"],
    }

    response = client.post("/api/v2/operator", json=command, headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "command_unavailable"

    assert client.post(
        "/api/v2/operator",
        json={**command, "actor_role": "judge_operator"},
        headers=headers,
    ).status_code == 422
    assert client.post(
        "/api/v2/operator",
        json={**command, "kind": "automatic_bet"},
        headers=headers,
    ).status_code == 422
