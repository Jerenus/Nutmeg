# Notification Delivery Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Nutmeg's duplicated Telegram report senders with a durable, idempotent notification kernel while preserving the live decision and Zucai CLI contracts.

**Architecture:** Business services render reports and submit a normalized `NotificationRequest`. A synchronous `NotificationService` snapshots attachments, persists notification/delivery/attempt state in the existing SQLite state database, and calls a channel-specific Telegram provider with bounded retries. Existing CLI text and report JSON remain compatible while structured results and reliable exit codes replace scheduler string parsing.

**Tech Stack:** Python 3.12, dataclasses, SQLAlchemy 2, SQLite, httpx, Typer, pytest, existing `TelegramBotClient` and report generators.

---

## File Structure

New focused modules:

- `nutmeg/notifications/__init__.py`: stable public exports.
- `nutmeg/notifications/models.py`: enums and immutable request/outcome value objects.
- `nutmeg/notifications/artifacts.py`: immutable attachment snapshots and hashes.
- `nutmeg/notifications/repository.py`: SQLAlchemy persistence operations and audit queries.
- `nutmeg/notifications/telegram.py`: Telegram error classification and provider adapter.
- `nutmeg/notifications/service.py`: dedupe, delivery state machine, retries, aggregation.
- `nutmeg/notifications/wiring.py`: settings-to-repository/provider/recipient assembly.
- `nutmeg/interfaces/cli/notifications.py`: status, show, and retry commands.
- `tests/test_notification_models.py`: fingerprint/outcome/artifact behavior.
- `tests/test_notification_repository.py`: schema, transitions, revision and audit queries.
- `tests/test_notification_service.py`: dedupe, partial failure, retries and uncertain recovery.
- `tests/test_notification_cli.py`: read-only operations and explicit retry commands.

Existing files modified:

- `nutmeg/storage/state_models.py`: four notification ORM tables.
- `nutmeg/interfaces/bot/telegram.py`: structured Telegram API errors without changing polling behavior.
- `nutmeg/interfaces/cli/__init__.py`: notification wiring exports and command registration.
- `nutmeg/decision/report.py`: semantic fingerprint, stage-aware publish, immutable notification outcome.
- `nutmeg/decision/verbs.py`: structured step/workflow result instead of swallowed string-only failure.
- `nutmeg/interfaces/cli/decision.py`: JSON format and nonzero required-delivery failures.
- `nutmeg/services/zucai.py`: replace local document dispatch with NotificationService.
- `nutmeg/services/zucai_renjiu_daily.py`: replace local document dispatch with NotificationService.
- `nutmeg/services/zucai_schedule.py`: pass the delivery stage and recognize standard success statuses.
- `nutmeg/interfaces/cli/zucai.py`: reliable nonzero exits while preserving report JSON.
- `scripts/openclaw/nutmeg_scheduler_ops.py`: consume decision JSON and publish deduplicated operations failure/recovery.
- Existing decision, Zucai, Telegram, CLI and scheduler tests: compatibility and integration assertions.

The current uncommitted scheduler/launchd work is user-owned. Modify it in place; do not revert its strict-stage, context, handoff or verification behavior.

### Task 1: Notification value objects and immutable artifacts

**Files:**
- Create: `nutmeg/notifications/__init__.py`
- Create: `nutmeg/notifications/models.py`
- Create: `nutmeg/notifications/artifacts.py`
- Create: `tests/test_notification_models.py`

- [ ] **Step 1: Write failing model and ArtifactStore tests**

```python
from pathlib import Path

import pytest

from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import (
    NotificationAttachment,
    NotificationRequest,
    NotificationStatus,
    semantic_fingerprint,
)


def test_semantic_fingerprint_ignores_mapping_order() -> None:
    assert semantic_fingerprint({"stage": "close", "items": [1, 2]}) == semantic_fingerprint(
        {"items": [1, 2], "stage": "close"}
    )


def test_request_builds_stable_dedupe_key(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-report")
    request = NotificationRequest(
        kind="decision.close.report",
        business_key="2026-07-17",
        stage="close",
        semantic_fingerprint="abc123",
        subject="Decision report",
        caption="Decision report 2026-07-17",
        attachments=(NotificationAttachment(report, "application/pdf"),),
    )
    assert request.dedupe_key == "decision.close.report:2026-07-17:close:abc123"
    assert NotificationStatus.SENT.is_success is True


def test_artifact_store_snapshots_once_and_rejects_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-report")
    store = ArtifactStore(tmp_path / "artifacts")
    stored = store.snapshot("N-1", NotificationAttachment(source, "application/pdf"))
    assert stored.path.read_bytes() == b"%PDF-report"
    assert stored.size_bytes == len(b"%PDF-report")
    assert len(stored.sha256) == 64
    with pytest.raises(FileExistsError):
        store.snapshot("N-1", NotificationAttachment(source, "application/pdf"))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_notification_models.py -q`  
Expected: collection fails because `nutmeg.notifications` does not exist.

- [ ] **Step 3: Implement immutable value objects and ArtifactStore**

Define string enums for notification/delivery/attempt status, frozen dataclasses for attachments, stored artifacts, targets, provider results, delivery outcomes and notification outcomes. Implement `semantic_fingerprint()` with canonical JSON (`sort_keys=True`, compact separators, UTF-8) and SHA-256. Implement `NotificationRequest.dedupe_key` exactly as asserted. Validate non-empty identity fields and at least one of text/attachments.

Provide explicit result constructors used throughout the plan:
`ProviderResult.sent()`, `ProviderResult.retryable_failure()`,
`ProviderResult.permanent_failure()`, and `NotificationOutcome.sent_for_test()`.
`NotificationOutcome.is_success` is true only for `sent`, `deduplicated`, and `dry_run`.

`ArtifactStore.snapshot()` must resolve the source, reject a missing/non-file source, create `<root>/<notification_id>/`, copy via an exclusive destination open (`"xb"`), and return the actual hash and byte count. Do not silently overwrite an audit artifact.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest tests/test_notification_models.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add nutmeg/notifications tests/test_notification_models.py
git commit -m "feat(notifications): add delivery value objects and artifact snapshots"
```

### Task 2: Durable notification repository

**Files:**
- Modify: `nutmeg/storage/state_models.py`
- Create: `nutmeg/notifications/repository.py`
- Create: `tests/test_notification_repository.py`

- [ ] **Step 1: Write failing repository lifecycle test**

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine

from nutmeg.notifications.models import DeliveryTarget, NotificationRequest
from nutmeg.notifications.repository import SqlAlchemyNotificationRepository
from nutmeg.storage.bootstrap import create_state_schema


def test_repository_creates_revision_and_records_attempt(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}", future=True)
    create_state_schema(engine)
    repo = SqlAlchemyNotificationRepository(engine)
    request = NotificationRequest.text(
        kind="operations.failure",
        business_key="decision-close:2026-07-17",
        stage="close",
        semantic_fingerprint="failure-a",
        subject="decision-close failed",
        text="capture-closing failed",
    )
    notification = repo.create_notification(
        request,
        targets=(DeliveryTarget("telegram", "owner", "7627818415", True),),
        artifacts=(),
    )
    delivery = repo.list_deliveries(notification.notification_id)[0]
    attempt = repo.start_attempt(delivery.delivery_id, started_at=datetime.now(UTC))
    repo.finish_attempt(
        attempt.attempt_id,
        delivered_at=datetime.now(UTC),
        provider_message_id="42",
    )
    bundle = repo.get_bundle(notification.notification_id)
    assert bundle.notification.revision == 1
    assert bundle.deliveries[0].status.value == "sent"
    assert bundle.attempts[0].provider_message_id == "42"


def test_repository_marks_stale_sending_uncertain(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}", future=True)
    create_state_schema(engine)
    repo = SqlAlchemyNotificationRepository(engine)
    request = NotificationRequest.text(
        kind="operations.failure",
        business_key="am:2026-07-17",
        stage="am",
        semantic_fingerprint="failure-b",
        subject="AM failed",
        text="fetch failed",
    )
    notification = repo.create_notification(
        request,
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        artifacts=(),
    )
    delivery = repo.list_deliveries(notification.notification_id)[0]
    repo.start_attempt(delivery.delivery_id, started_at=datetime.now(UTC) - timedelta(minutes=10))
    changed = repo.mark_stale_sending_uncertain(
        stale_before=datetime.now(UTC) - timedelta(minutes=5)
    )
    assert changed == 1
    assert repo.get_bundle(notification.notification_id).deliveries[0].status.value == "uncertain"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_notification_repository.py -q`  
Expected: import or missing-table failure.

- [ ] **Step 3: Add ORM tables and repository methods**

Add `NotificationRecord`, `NotificationArtifactRecord`, `NotificationDeliveryRecord`, and `NotificationAttemptRecord` to `state_models.py`. Use string primary keys, a unique dedupe key, indexed business/stage/status/timestamp columns, JSON stored as canonical text, and foreign keys with delete cascade. Include `revision` on notifications and a unique `(notification_id, channel, destination)` delivery constraint.

Implement repository methods used in the tests plus `get_by_dedupe_key()`,
`add_artifacts()`, `mark_delivery_failed()`, `aggregate_notification()`,
`list_recent()`, `list_retryable_required()`, and `get_bundle()`. Their return values are the
immutable `NotificationView`/`NotificationBundle` dataclasses defined in
`nutmeg.notifications.models`; list-returning methods always sort newest notification first and
attempts by ascending attempt number.

Every mutation opens a short SQLAlchemy session and commits before returning. `start_attempt()` sets the delivery to `sending` and commits before network I/O. `finish_attempt()` atomically marks attempt and delivery sent. Aggregation follows the approved required-delivery precedence.

- [ ] **Step 4: Run repository tests and existing schema tests**

Run: `uv run pytest tests/test_notification_repository.py tests/test_sync_service.py tests/test_prediction_repository.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add nutmeg/storage/state_models.py nutmeg/notifications/repository.py tests/test_notification_repository.py
git commit -m "feat(notifications): persist delivery and attempt audit state"
```

### Task 3: Telegram provider and delivery state machine

**Files:**
- Modify: `nutmeg/interfaces/bot/telegram.py`
- Create: `nutmeg/notifications/telegram.py`
- Create: `nutmeg/notifications/service.py`
- Create: `nutmeg/notifications/wiring.py`
- Create: `tests/test_notification_service.py`
- Modify: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write failure-injection tests**

```python
from pathlib import Path

from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import (
    DeliveryTarget,
    NotificationAttachment,
    NotificationRequest,
    ProviderResult,
)
from nutmeg.notifications.service import NotificationService


class ScriptedProvider:
    channel = "telegram"

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def send(self, *, target, request, artifacts):
        self.calls.append(target.destination)
        return self.results.pop(0)

    def send_fallback(self, *, target, request, error):
        return ProviderResult.sent("fallback-1")


def test_service_deduplicates_success(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider([ProviderResult.sent("message-1")])
    service = NotificationService(
        repository=repository,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        providers={"telegram": provider},
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        sleep_fn=lambda _seconds: None,
    )
    request = NotificationRequest.text(
        kind="operations.failure",
        business_key="am:2026-07-17",
        stage="am",
        semantic_fingerprint="same",
        subject="AM failed",
        text="fetch failed",
    )
    assert service.publish(request).status.value == "sent"
    assert service.publish(request).status.value == "deduplicated"
    assert provider.calls == ["1"]


def test_service_isolates_partial_failure(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        ProviderResult.sent("message-1"),
        ProviderResult.permanent_failure("invalid_chat", "chat not found"),
    ])
    service = NotificationService(
        repository=repository,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        providers={"telegram": provider},
        targets=(
            DeliveryTarget("telegram", "owner-a", "1", True),
            DeliveryTarget("telegram", "owner-b", "2", True),
        ),
        sleep_fn=lambda _seconds: None,
    )
    outcome = service.publish(NotificationRequest.text(
        kind="operations.failure",
        business_key="close:2026-07-17",
        stage="close",
        semantic_fingerprint="partial",
        subject="Close failed",
        text="report failed",
    ))
    assert outcome.status.value == "partial"
    assert [item.status.value for item in outcome.deliveries] == ["sent", "permanent_failed"]


def test_service_retries_transient_only(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        ProviderResult.retryable_failure("timeout", "timed out", retry_after_seconds=0),
        ProviderResult.sent("message-2"),
    ])
    service = NotificationService(
        repository=repository,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        providers={"telegram": provider},
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        sleep_fn=lambda _seconds: None,
    )
    outcome = service.publish(NotificationRequest.text(
        kind="operations.failure",
        business_key="settle:2026-07-17",
        stage="settle",
        semantic_fingerprint="retry",
        subject="Settle failed",
        text="network timeout",
    ))
    assert outcome.status.value == "sent"
    assert provider.calls == ["1", "1"]
```

Use this fixture in the service test module:

```python
import pytest
from sqlalchemy import create_engine

from nutmeg.notifications.repository import SqlAlchemyNotificationRepository
from nutmeg.storage.bootstrap import create_state_schema


@pytest.fixture
def repository():
    engine = create_engine("sqlite:///:memory:", future=True)
    create_state_schema(engine)
    return SqlAlchemyNotificationRepository(engine)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_notification_service.py -q`  
Expected: missing provider/service failures.

- [ ] **Step 3: Implement structured Telegram errors and provider**

Add `TelegramApiError(RuntimeError)` carrying `status_code`, `error_code`, `description`, and `retry_after_seconds`. Keep it a `RuntimeError` subclass for compatibility. Centralize payload validation in `TelegramBotClient`; preserve current successful return values and bot polling API.

Implement `TelegramProvider.send()` to validate text/caption and artifact paths before calling the client. Classify 429 as `rate_limited`, request/timeout and 5xx as retryable, and other 4xx/API validation as permanent. Extract `result.message_id` as a string. Implement `send_fallback()` with `send_message` and no local path disclosure.

- [ ] **Step 4: Implement NotificationService**

Implement the tested constructor and `publish(request, dry_run=False)`. Dry-run returns target plans without calling repository or provider. Real publish snapshots artifacts only for a new notification, creates deliveries, commits `sending` before each provider call, retries no more than three total calls, skips already-sent deliveries, records fallback attempts separately, aggregates, and returns `NotificationOutcome`.

Add `retry(notification_id, include_permanent=False)` and `retry_failed_required()` using the same state machine. On startup/publish, convert stale `sending` deliveries to `uncertain`; retry them with `possible_duplicate=True` on the new attempt.

`wiring.build_notification_service(settings=None)` must build the existing state engine/schema, repository, `.nutmeg-data/notifications/artifacts` store, Telegram client/provider, and sorted configured owner targets. It must never log the token.

- [ ] **Step 5: Run provider, service and legacy Telegram tests**

Run: `uv run pytest tests/test_notification_service.py tests/test_telegram_bot.py -q`  
Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add nutmeg/interfaces/bot/telegram.py nutmeg/notifications tests/test_notification_service.py tests/test_telegram_bot.py
git commit -m "feat(notifications): deliver Telegram reports with retries and dedupe"
```

### Task 4: Notification audit and retry CLI

**Files:**
- Create: `nutmeg/interfaces/cli/notifications.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Create: `tests/test_notification_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_notification_status_json_uses_redacted_destinations(monkeypatch) -> None:
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.notifications._status_payload",
        lambda since: {
            "since": since,
            "counts": {"sent": 1},
            "notifications": [{"notification_id": "N-1", "destination": "***8415"}],
        },
    )
    result = runner.invoke(app, ["notification-status", "--since", "7d", "--format", "json"])
    assert result.exit_code == 0
    assert "***8415" in result.output
    assert "7627818415" not in result.output


def test_notification_retry_requires_explicit_selector() -> None:
    result = runner.invoke(app, ["notification-retry"])
    assert result.exit_code == 2
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_notification_cli.py -q`  
Expected: commands are not registered.

- [ ] **Step 3: Implement status/show/retry commands**

Register `notification-status`, `notification-show`, and `notification-retry`. Parse `--since` values ending in `h` or `d`, reject non-positive durations, and use the repository/service from notification wiring. Text and JSON output must redact destinations to the last four characters. `notification-retry` accepts exactly one of `--notification-id` or `--failed-required`; permanent failures require `--include-permanent`; uncertain results display `possible_duplicate=true`. Return exit code 1 if any required delivery remains unsuccessful.

- [ ] **Step 4: Run CLI tests and global help smoke**

Run: `uv run pytest tests/test_notification_cli.py -q && uv run nutmeg --help >/dev/null`  
Expected: tests and help command succeed.

- [ ] **Step 5: Commit Task 4**

```bash
git add nutmeg/interfaces/cli/__init__.py nutmeg/interfaces/cli/notifications.py tests/test_notification_cli.py
git commit -m "feat(cli): expose notification audit and retry commands"
```

### Task 5: Decision report and workflow integration

**Files:**
- Modify: `nutmeg/decision/report.py`
- Modify: `nutmeg/decision/verbs.py`
- Modify: `nutmeg/interfaces/cli/decision.py`
- Modify: `tests/decision/test_report.py`
- Modify: `tests/decision/test_daily.py`
- Modify: `tests/decision/test_m1_verbs.py`

- [ ] **Step 1: Write failing decision integration tests**

Add tests asserting:

```python
def test_close_and_settle_use_distinct_notification_stages(tmp_path, monkeypatch):
    stages = []

    def fake_report(run_date, output_dir, *, dispatch_telegram, dry_run, stage):
        stages.append(stage)
        return DecisionReportResult.success(
            run_date=run_date,
            pdf_path=tmp_path / f"{stage}.pdf",
            pdf_bytes=10,
        )

    monkeypatch.setattr(verbs, "run_capture_closing", lambda *args: "closing-ok")
    monkeypatch.setattr(verbs, "run_reconcile", lambda *args: "reconcile-ok")
    monkeypatch.setattr(verbs, "run_calibrate_panel", lambda *args: "calibrate-ok")
    monkeypatch.setattr(verbs, "run_report", fake_report)
    verbs.run_decision_close("2026-07-17", tmp_path)
    verbs.run_decision_settle("2026-07-17", tmp_path)
    assert stages == ["close", "settle"]


def test_decision_close_json_failure_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verbs,
        "run_decision_close",
        lambda *args, **kwargs: DecisionWorkflowResult.failed(
            "decision-close", "2026-07-17", "report", "Telegram delivery failed"
        ),
    )
    result = runner.invoke(app, [
        "decision-close", "--run-date", "2026-07-17",
        "--output-dir", str(tmp_path), "--format", "json",
    ])
    assert result.exit_code == 1
    assert '"status": "failed"' in result.output
```

Also extend `test_report.py` with a fake NotificationService proving the normalized `_report_blocks` fingerprint deduplicates identical content and that the compatibility PDF path still exists.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/decision/test_report.py tests/decision/test_daily.py -q`  
Expected: missing stage/result APIs.

- [ ] **Step 3: Implement DecisionReportResult and publish**

Replace the old `dispatch()` helper with a `DecisionReportResult` carrying run date, stage, PDF path/size and optional `NotificationOutcome`. Compute the semantic fingerprint from `_report_blocks(store, run_date)` plus the explicit stage, not from PDF bytes. Preserve the compatibility PDF write. When dispatch is requested, call an injected NotificationService or the wiring builder with a PDF request and `business_key=run_date`. Direct `decision-report` defaults to `stage=manual`.

- [ ] **Step 4: Implement structured workflow results and CLI**

Add immutable `DecisionStepResult` and `DecisionWorkflowResult` in `verbs.py`. `_compose()` captures each exception as a failed step, normalizes report outcomes, and exposes `to_dict()`, `__str__()`, `__contains__()` and `succeeded`. Preserve best-effort execution of later deterministic steps but make the aggregate failure visible.

Add `--format text|json` to decision report/close/settle. Print the result before raising `typer.Exit(1)` when it is unsuccessful. Existing defaults and flags remain unchanged.

- [ ] **Step 5: Run all decision tests**

Run: `uv run pytest tests/decision -q`  
Expected: all decision tests pass without network access.

- [ ] **Step 6: Commit Task 5**

```bash
git add nutmeg/decision/report.py nutmeg/decision/verbs.py nutmeg/interfaces/cli/decision.py tests/decision
git commit -m "refactor(decision): route reports through notification ledger"
```

### Task 6: Zucai report integration and compatibility

**Files:**
- Modify: `nutmeg/services/zucai.py`
- Modify: `nutmeg/services/zucai_renjiu_daily.py`
- Modify: `nutmeg/services/zucai_schedule.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Modify: `nutmeg/interfaces/cli/zucai.py`
- Modify: `tests/test_zucai_service.py`
- Modify: `tests/test_zucai_renjiu_daily.py`
- Modify: `tests/test_zucai_schedule_service.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Replace dry-run-only tests with standard outcome integration tests**

Use a recording fake NotificationService:

```python
class RecordingNotificationService:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def publish(self, request, *, dry_run=False):
        self.calls.append((request, dry_run))
        return self.outcome


def test_zucai_dispatch_maps_standard_outcome(tmp_path):
    notifier = RecordingNotificationService(NotificationOutcome.sent_for_test("N-1", "91"))
    report = ZucaiWorkflowService(notification_service=notifier).build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        dispatch_telegram=True,
        dry_run=False,
        notification_stage="manual",
    )
    assert report.dispatch.status == "sent"
    assert report.dispatch.document_path == report.artifacts.pdf_path
    assert notifier.calls[0][0].business_key == "26068"
```

Add corresponding Renjiu and scheduled afternoon/revision stage tests. Add CLI tests proving failed required delivery exits 1 after emitting JSON.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/test_zucai_service.py tests/test_zucai_renjiu_daily.py tests/test_zucai_schedule_service.py -q`  
Expected: constructors/stage arguments are missing.

- [ ] **Step 3: Replace local dispatch methods**

Inject NotificationService into both report services. Build fingerprints from report `to_dict()` after removing `generated_at`, `dispatch`, and artifact paths. Submit the rendered PDF with issue ID as business key and the supplied stage. Convert `NotificationOutcome.to_compat_dispatch()` into the existing `ZucaiDispatch`/`RenjiuDispatch` dataclasses. Remove sender protocols, sender/chat-id fields, and `_dispatch()` implementations.

Pass the schedule slot into `notification_stage`. Treat `sent`, `deduplicated`, and `dry_run` as completed scheduled statuses; `partial`, `failed`, and `uncertain` are failures.

Update CLI builders to inject one wired NotificationService. Preserve command flags and report payload shape. Exit 1 only for requested non-dry required delivery failure.

- [ ] **Step 4: Run Zucai and CLI regression tests**

Run: `uv run pytest tests/test_zucai_service.py tests/test_zucai_renjiu_daily.py tests/test_zucai_schedule_service.py tests/test_cli.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

```bash
git add nutmeg/services/zucai.py nutmeg/services/zucai_renjiu_daily.py nutmeg/services/zucai_schedule.py nutmeg/interfaces/cli tests/test_zucai* tests/test_cli.py
git commit -m "refactor(zucai): unify formal report notification delivery"
```

### Task 7: Structured scheduler failures and recovery

**Files:**
- Modify: `scripts/openclaw/nutmeg_scheduler_ops.py`
- Modify: `tests/test_nutmeg_scheduler_ops.py`
- Modify: `docs/nutmeg-scheduler-operations.md`

- [ ] **Step 1: Write scheduler JSON and failure-notification tests**

```python
def test_run_strict_uses_structured_decision_result(monkeypatch, tmp_path):
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout=json.dumps({
            "status": "failed",
            "steps": [{"label": "report", "status": "failed", "message": "delivery failed"}],
        }),
        stderr="",
    )
    monkeypatch.setattr(ops, "_run", lambda command: completed)
    sent = []
    monkeypatch.setattr(ops, "_publish_operation_event", lambda **payload: sent.append(payload))
    with pytest.raises(ops.SchedulerError):
        ops.run_strict("close", "2026-07-17", tmp_path)
    assert sent[0]["kind"] == "operations.failure"


def test_success_after_failure_publishes_recovery_once(monkeypatch, tmp_path):
    state = tmp_path / "operation-events.json"
    state.write_text(json.dumps({"close:2026-07-17": "failed"}))
    sent = []
    monkeypatch.setattr(ops, "_publish_operation_event", lambda **payload: sent.append(payload))
    ops._record_operation_success("close", "2026-07-17", state)
    assert sent[0]["kind"] == "operations.recovered"
```

- [ ] **Step 2: Run scheduler tests and verify RED**

Run: `uv run pytest tests/test_nutmeg_scheduler_ops.py -q`  
Expected: structured event helpers are missing.

- [ ] **Step 3: Consume JSON and publish operation events**

Invoke decision stages with `--format json`. Parse exactly one JSON object; failure is determined by return code or payload status, never marker text. On an upstream/report failure, call notification wiring with a text `NotificationRequest` whose fingerprint is the SHA-256 of the normalized failed step labels/messages. Do not publish another operation event when the failed step is already a Telegram delivery failure. Persist only the small failure/recovery dedupe state under `.nutmeg-data/state/scheduler-operation-events.json`.

Preserve all current handoff, context, settlement retry and close verification behavior. Change `verify_close()` to query the notification ledger for a sent `decision.close.report` matching the run date instead of trusting a mutable PDF plus log substring.

- [ ] **Step 4: Run scheduler tests and dry command help**

Run: `uv run pytest tests/test_nutmeg_scheduler_ops.py -q && uv run python scripts/openclaw/nutmeg_scheduler_ops.py --help >/dev/null`  
Expected: all tests and help pass.

- [ ] **Step 5: Update operations documentation**

Document structured JSON status, notification ledger verification, failure/recovery dedupe, retry commands, and the rule that Telegram transport failures do not recursively alert.

- [ ] **Step 6: Commit Task 7 without staging unrelated launchd/SOUL changes**

```bash
git add scripts/openclaw/nutmeg_scheduler_ops.py tests/test_nutmeg_scheduler_ops.py docs/nutmeg-scheduler-operations.md
git commit -m "refactor(ops): verify scheduled delivery from notification ledger"
```

### Task 8: Cleanup, end-to-end dry replay and full verification

**Files:**
- Modify: `README.md`
- Modify: notification/decision/Zucai tests if verification exposes contract gaps

- [ ] **Step 1: Prove duplicate dispatch implementations are gone from live report paths**

Run:

```bash
rg -n "def _dispatch\(|_resolve_telegram\(|telegram_sender|telegram_chat_ids" \
  nutmeg/decision/report.py nutmeg/services/zucai.py nutmeg/services/zucai_renjiu_daily.py
```

Expected: no matches. Do not remove excluded legacy `DailyOperatorService`, polling bot, client Alert or one-off scripts.

- [ ] **Step 2: Run focused quality gates**

Run:

```bash
uv run ruff check \
  nutmeg/notifications nutmeg/decision/report.py nutmeg/decision/verbs.py \
  nutmeg/interfaces/cli/notifications.py nutmeg/interfaces/cli/decision.py \
  nutmeg/interfaces/cli/zucai.py nutmeg/services/zucai.py \
  nutmeg/services/zucai_renjiu_daily.py nutmeg/services/zucai_schedule.py \
  tests/test_notification_models.py tests/test_notification_repository.py \
  tests/test_notification_service.py tests/test_notification_cli.py
uv run pytest \
  tests/test_notification_models.py tests/test_notification_repository.py \
  tests/test_notification_service.py tests/test_notification_cli.py \
  tests/decision tests/test_zucai_service.py tests/test_zucai_renjiu_daily.py \
  tests/test_zucai_schedule_service.py tests/test_telegram_bot.py \
  tests/test_nutmeg_scheduler_ops.py tests/test_cli.py -q
```

Expected: ruff clean and all focused tests pass.

- [ ] **Step 3: Run isolated end-to-end dry replay**

Use a temporary output directory and never pass `--no-dry-run`:

```bash
tmpdir=$(mktemp -d)
uv run nutmeg decision-report --date 2026-07-16 --output-dir .nutmeg-data/jczq \
  --dispatch-telegram --dry-run --format json
uv run nutmeg zucai-report --issue-id 26068 --output-dir "$tmpdir/zucai" \
  --pdf --dispatch-telegram --dry-run --format json
uv run nutmeg notification-status --since 1d --format json
```

Expected: both report commands return success with `dry_run`, no Telegram call occurs, and dry-run creates no notification rows or immutable artifacts.

- [ ] **Step 4: Run full project verification**

Run:

```bash
uv run ruff check .
uv run pytest -q
scripts/verify.sh
```

Expected: every command exits 0. If `scripts/verify.sh` contains environment-dependent checks, report the exact skipped/unavailable check and retain all deterministic test evidence.

- [ ] **Step 5: Update README and perform spec coverage self-check**

Document the three notification audit/retry commands, immutable artifact location, at-least-once limitation, and explicit confirmation requirement for live smoke. Cross-check every acceptance criterion in `docs/superpowers/specs/2026-07-17-notification-delivery-kernel-design.md` against tests or dry-run evidence.

- [ ] **Step 6: Commit final documentation and contract adjustments**

```bash
git add README.md nutmeg tests
git commit -m "docs: document reliable notification operations"
```

## Completion Gate

Do not claim the live cutover verified until the user separately authorizes one real Telegram smoke. The code refactor is complete when all deterministic gates pass, the live commands use only NotificationService, and the remaining unverified item is explicitly reported as “real Telegram smoke pending authorization.”
