from __future__ import annotations

import re
import socket
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from playwright.sync_api import Page, sync_playwright
from pydantic import ValidationError

from nutmeg.interfaces.operator_api import (
    GradePredictionCommandV2,
    RecordScoreboardEffectDispositionCommandV2,
)
from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    RegisterPredictionRequest,
    WorkflowActions,
)
from nutmeg.ontology.operator.review_actions import (
    MaterializeOperatorReviewItemRequest,
    OperatorReviewActions,
    ShadowReviewTokenCodec,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    ReviewAdjudicationSummary,
    ReviewCompletionGateSummary,
    ReviewEvidenceOptionSummary,
    ReviewForecastSummary,
    ReviewInterventionSummary,
    ReviewMoneySummary,
    ReviewScoreboardObservationSummary,
    ReviewShadowOptionSummary,
    ReviewStep,
    TaskProgressSummary,
)
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import (
    ConfirmationDeadlineWorker,
    ReviewMaterializationWorker,
)
from nutmeg.product.repository import ProductReadRepository
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.operator.test_no_ticket_actions import _artifact_fixture
from tests.ontology.operator.test_review_actions import (
    _materialized_review,
    _seed_bound_outcome,
)
from tests.product.operator_v2.test_confirmation_lifecycle import _protected

NOW = datetime(2026, 9, 5, 9, tzinfo=UTC)
TASK_KEY = "zucai:26116"
TOKEN_KEY = b"package-eleven-review-ui-token-key"


class _ProjectionReadyRepository(ProductReadRepository):
    def scoreboard_projection(self, *, as_of: str) -> dict[str, object]:
        del as_of
        return {
            "health": {
                "state": "available",
                "source_high_watermark": self.action_high_watermark(),
            },
            "rows": [],
        }


def _step() -> ReviewStep:
    return ReviewStep(
        surface_version="2",
        task_id=TASK_KEY,
        title="本期复盘",
        review_kind="forecast_truth",
        review_state="pending",
        scoreboard_projection_state="ready",
        forecast_truth=[
            ReviewForecastSummary(
                title="至少一场平局",
                falsifier="全部场次均非平局",
                state="pending",
                prediction_review_token="opaque.prediction-reference",
                grade_command_token="opaque.grade-command",
            )
        ],
        money_ledger=ReviewMoneySummary(
            state="settled",
            currency="CNY",
            stake_minor=400,
            payout_minor=760,
            pnl_minor=360,
            ticket_count=1,
        ),
        intervention_quality=ReviewInterventionSummary(
            disposition="effect_required",
            reason="本次人工干预需要进入治理观察。",
            required_metric_keys=["user_naked_wheels"],
            linked_metric_keys=[],
            review_token="opaque.review-reference",
            disposition_token="opaque.disposition-reference",
            effect_command_token="opaque.effect-command",
            observation_command_token="opaque.observation-command",
            completion_command_token="opaque.completion-command",
            evidence_options=[
                ReviewEvidenceOptionSummary(
                    label="预注册预测：至少一场平局",
                    token="opaque.review-evidence",
                )
            ],
            shadow_options=[
                ReviewShadowOptionSummary(
                    label="2026-09-05 影子核对",
                    state="ready",
                    token="opaque.signed-shadow-review",
                )
            ],
        ),
        adjudication_history=[
            ReviewAdjudicationSummary(
                decision="approve",
                reason="采用本期已核对的结构。",
                rejected_evidence_count=1,
                created_at=NOW - timedelta(hours=2),
            )
        ],
        scoreboard_observation_history=[
            ReviewScoreboardObservationSummary(
                metric_key="user_naked_wheels",
                tally="1/3",
                detail="本期人工干预已进入正式治理观察。",
                status="formal_manual",
                numerator_decimal="1",
                denominator_decimal="3",
                value_decimal=None,
                unit="count",
                effective_at=NOW - timedelta(hours=1),
            )
        ],
        completion_gates=[
            ReviewCompletionGateSummary(
                gate="legacy_update",
                label="旧记分牌更新已观察",
                state="complete",
                detail="已观察到更新后的权威文件。",
            ),
            ReviewCompletionGateSummary(
                gate="observations",
                label="所需观察已提交",
                state="pending",
                detail="还需提交 1 项治理观察。",
            ),
            ReviewCompletionGateSummary(
                gate="shadow_reconciliation",
                label="所选影子核对有效",
                state="pending",
                detail="等待选择并提交一份有效影子核对。",
            ),
        ],
        maintenance_href="/operator-next/maintenance",
    )


class _Queries:
    def __init__(self, step: ReviewStep) -> None:
        selected = OperatorTaskSummary(
            task_id=step.task_id,
            lane=OperatorLane.ZUCAI,
            business_key="26116",
            title="足彩 26116",
            state=OperatorTaskState.REVIEW,
            deadline_at=NOW - timedelta(days=1),
            is_actionable=True,
            next_action_label="继续复盘",
            priority_rank=0,
        )
        self.response = OperatorTaskResponse(
            as_of=NOW,
            mutation_token="d" * 64,
            selected=selected,
            alternatives=[],
            progress=TaskProgressSummary(completed=1, total=3, label="复盘"),
            step=step,
        )

    def task(self, _task_id: str, *, as_of):
        return self.response

    def worklist(self, *, as_of):
        return SimpleNamespace(selected=self.response.selected, tasks=[], as_of=as_of)


def _html(step: ReviewStep | None = None, *, read_only: bool = False) -> str:
    app = FastAPI()
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(step or _step())),
        lambda: NOW,
        read_only=read_only,
    )
    response = TestClient(app).get(f"/tasks/{TASK_KEY}")
    assert response.status_code == 200
    return response.text


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def review_browser_page():
    app = FastAPI()
    asset_root = (
        Path(__file__).resolve().parents[3]
        / "nutmeg"
        / "interfaces"
        / "web"
        / "static"
        / "product"
    )
    app.mount(
        "/assets/product",
        StaticFiles(directory=asset_root),
        name="product-assets",
    )
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(_step())),
        lambda: NOW,
        read_only=False,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            yield page, f"http://127.0.0.1:{port}"
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_review_surface_separates_truth_money_and_intervention_with_ordered_gates() -> None:
    html = _html()

    headings = [
        "预测真值",
        "资金账",
        "干预质量",
        "本期裁决",
        "<h3>治理观察</h3>",
        "旧记分牌更新已观察",
        "所需观察已提交",
        "所选影子核对有效",
    ]
    assert all(label in html for label in headings)
    assert [html.index(label) for label in headings] == sorted(
        html.index(label) for label in headings
    )
    for visible in (
        "至少一场平局",
        "全部场次均非平局",
        "¥4.00",
        "¥7.60",
        "+¥3.60",
        "本次人工干预需要进入治理观察",
        "user_naked_wheels",
        "采用本期已核对的结构。",
        "拒绝证据 1 项",
        "本期人工干预已进入正式治理观察。",
        "正式人工观察",
    ):
        assert visible in html


def test_review_surface_exposes_only_named_actions_and_external_maintenance_link() -> None:
    html = _html()

    assert 'data-action="grade-prediction-v2"' in html
    assert 'data-action="record-scoreboard-effect"' in html
    assert 'data-action="record-scoreboard-observation"' in html
    assert 'data-action="request-scoreboard-review-completion"' in html
    assert 'href="/operator-next/maintenance"' in html
    assert "更新记分牌文件" not in html
    assert "执行 cutover" not in html
    assert 'data-action="scoreboard-cutover"' not in html
    assert 'data-action="write-scoreboard"' not in html


def test_review_surface_hides_json_internal_ids_hashes_roles_and_schema_names() -> None:
    html = _html()

    assert "<pre" not in html
    assert "{" not in html
    assert not re.search(r"\b[0-9a-f]{64}\b", html)
    for forbidden in (
        "review_id",
        "prediction_id",
        "disposition_revision_id",
        "scoreboard_observation_id",
        "shadow_review_id",
        "action_id",
        "legacy_sha256",
        "schema_version",
        'name="actor_id"',
        'name="actor_role"',
        "judge_operator",
        "deterministic_system",
    ):
        assert forbidden not in html


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hit_count", 1),
        ("total_count", 2),
        ("stake_yuan", 4.0),
        ("payout_yuan", 7.6),
        ("pnl_yuan", 3.6),
        ("calibration_summary", "legacy untyped summary"),
        (
            "current_item",
            {
                "item_type": "prediction",
                "item_id": "prediction-raw-id",
                "title": "legacy current item",
                "allowed_outcomes": ["hit", "miss", "na"],
            },
        ),
    ),
)
def test_v2_review_contract_rejects_every_legacy_field(field: str, value: object) -> None:
    payload = _step().model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValidationError):
        ReviewStep.model_validate(payload)


def test_read_only_review_surface_has_no_mutation_forms() -> None:
    html = _html(read_only=True)

    assert "预测真值" in html
    assert "资金账" in html
    assert "干预质量" in html
    assert "只读模式" in html
    assert "data-action=" not in html


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_review_surface_is_nonblank_and_overlap_free_at_both_viewports(
    review_browser_page: tuple[Page, str],
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    page, base_url = review_browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + f"/tasks/{TASK_KEY}", wait_until="networkidle")

    assert "Inter" in page.locator("body").evaluate(
        "element => getComputedStyle(element).fontFamily"
    )
    assert page.get_by_role("heading", name="预测真值", exact=True).count() == 1
    assert page.get_by_role("heading", name="资金账", exact=True).count() == 1
    assert page.get_by_role("heading", name="干预质量", exact=True).count() == 1
    assert page.locator("pre").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    header = page.locator(".operator-header").bounding_box()
    main = page.locator("#main-content").bounding_box()
    assert header and main and header["y"] + header["height"] <= main["y"]
    for form in page.locator("form[data-action]").all():
        box = form.bounding_box()
        button = form.locator("button[type='submit']").bounding_box()
        assert box and button
        assert button["x"] >= box["x"]
        assert button["x"] + button["width"] <= box["x"] + box["width"] + 1
    screenshot = tmp_path / f"operator-review-{width}x{height}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    assert screenshot.stat().st_size > 5_000
    with Image.open(screenshot).convert("RGB") as rendered:
        background = Image.new("RGB", rendered.size, rendered.getpixel((0, 0)))
        assert ImageChops.difference(rendered, background).getbbox() is not None


def test_review_javascript_posts_only_the_four_closed_review_commands() -> None:
    script = (
        Path(__file__).parents[3]
        / "nutmeg/interfaces/web/static/product/operator.js"
    ).read_text(encoding="utf-8")

    for action, kind in (
        ("grade-prediction-v2", "grade_prediction"),
        ("record-scoreboard-effect", "record_scoreboard_effect_disposition"),
        ("record-scoreboard-observation", "record_scoreboard_observation"),
        (
            "request-scoreboard-review-completion",
            "request_scoreboard_review_completion",
        ),
    ):
        assert f'action === "{action}"' in script
        assert f'kind: "{kind}"' in script
    review_script = script[
        script.index('action === "grade-prediction-v2"') :
        script.index('action === "record-no-ticket"')
    ]
    assert "prediction_id" not in review_script
    assert "review_id" not in review_script
    assert "disposition_revision_id" not in review_script
    assert "actor_role" not in review_script
    assert "legacy_sha256" not in review_script


def _materialize_additional_review(fixture) -> str:
    with OntologyUnitOfWork(fixture.engine) as uow:
        original = uow.operator_review.eligibility_fact(fixture.fact_id)
        assert original is not None
        second_fact_id = "review-eligibility-second-work-item"
        uow.operator_result.insert_review_eligibility_fact(
            replace(
                original,
                review_eligibility_fact_id=second_fact_id,
                fact_index=original.fact_index + 1,
                content_hash="e" * 64,
                created_at=(AT + timedelta(minutes=4)).isoformat(),
            )
        )
    with OntologyUnitOfWork(fixture.engine) as uow:
        second_job = uow.operator_decision.worker_job_for_source(
            job_kind="review_materialization",
            source_object_type="operator_review_eligibility_fact",
            source_object_id=second_fact_id,
        )
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="review_materialization",
            lease_owner="second-review-worker",
            as_of=(AT + timedelta(minutes=5)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=10)).isoformat(),
            limit=1,
        )
    assert second_job is not None and [job.worker_job_id for job in claimed] == [
        second_job.worker_job_id
    ]
    materialized = fixture.actions.materialize_operator_review_item(
        MaterializeOperatorReviewItemRequest(
            review_eligibility_fact_id=second_fact_id,
            worker_job_id=second_job.worker_job_id,
            lease_owner="second-review-worker",
            actor_id="system:operator-review",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            requested_at=AT + timedelta(minutes=6),
        )
    )
    return next(
        ref.object_id
        for ref in materialized.result_refs
        if ref.object_type == "operator_review_item"
    )


def test_materialized_review_without_baseline_reenters_today_as_review(tmp_path: Path) -> None:
    fixture, _review_id = _materialized_review(tmp_path)
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(days=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )

    task = queries.task("jczq:2026-09-04", as_of=AT + timedelta(days=1))
    today = queries.today(as_of=AT + timedelta(days=1))
    lane = queries.lane(OperatorLane.JCZQ, as_of=AT + timedelta(days=1))
    detail = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=AT + timedelta(days=1),
    )

    assert task.selected.state is OperatorTaskState.REVIEW
    assert isinstance(task.step, ReviewStep)
    assert task.step.surface_version == "2"
    assert task.step.review_kind == "operational_data_availability"
    review_entries = [
        entry for entry in today.entries if entry.kind == "today_work_item_v1"
    ]
    assert [entry.business_key for entry in review_entries] == ["2026-09-04"]
    assert review_entries[0].scope_kind == "review"
    assert detail.active_work_item.scope_kind == "review"
    expired_wave = next(
        item for item in detail.work_items if item.scope_kind == "sale_wave"
    )
    assert expired_wave.phase == "complete"
    assert expired_wave.deployment_outcome == "expired"
    assert expired_wave.next_action is None
    assert lane.current_tasks == []
    assert [item.business_key for item in lane.archive_tasks] == ["2026-09-04"]


def test_all_pending_reviews_for_one_task_are_independent_today_work_items(
    tmp_path: Path,
) -> None:
    fixture, first_review_id = _materialized_review(tmp_path)
    second_review_id = _materialize_additional_review(fixture)
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(days=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )

    built = queries._build_all(AT + timedelta(days=1))
    today = queries.today(as_of=AT + timedelta(days=1))
    detail = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=AT + timedelta(days=1),
    )

    review_steps = [item for item in built if isinstance(item.step, ReviewStep)]
    review_entries = [
        entry
        for entry in today.entries
        if entry.kind == "today_work_item_v1" and entry.scope_kind == "review"
    ]
    review_children = [
        item for item in detail.work_items if item.scope_kind == "review"
    ]
    assert first_review_id != second_review_id
    assert len(review_steps) == 2
    assert len(review_entries) == 2
    assert len(review_children) == 2
    assert len({item.work_item_key for item in review_children}) == 2


def test_second_review_page_token_mutates_only_the_second_review(tmp_path: Path) -> None:
    fixture, first_review_id = _materialized_review(tmp_path)
    second_review_id = _materialize_additional_review(fixture)
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    snapshot_tokens = OperatorSnapshotTokenCodec(TOKEN_KEY)
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(days=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=snapshot_tokens,
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_text('{"authority":"legacy"}\n', encoding="utf-8")
    actions = OperatorActionService(
        queries=queries,
        action_gateway=SimpleNamespace(),
        review_actions=fixture.actions,
        snapshot_tokens=snapshot_tokens,
        repository=repository,
        scoreboard_path=scoreboard,
        clock=lambda: AT + timedelta(days=1),
    )
    task = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=AT + timedelta(days=1),
    )
    second_step = None
    for child in task.work_items:
        if child.scope_kind != "review":
            continue
        page = queries.work_item_v2(
            OperatorLane.JCZQ,
            "2026-09-04",
            child.work_item_key,
            as_of=AT + timedelta(days=1),
        )
        assert isinstance(page.step, ReviewStep)
        intervention = page.step.intervention_quality
        assert intervention is not None and intervention.effect_command_token
        payload = snapshot_tokens.decode(intervention.effect_command_token)
        if payload.work_item_id.endswith(f":{second_review_id}"):
            second_step = page.step
            break
    assert second_step is not None and second_step.intervention_quality is not None
    intervention = second_step.intervention_quality

    completed = actions.record_scoreboard_effect_disposition(
        RecordScoreboardEffectDispositionCommandV2(
            schema_version="2",
            kind="record_scoreboard_effect_disposition",
            expected_snapshot_token=intervention.effect_command_token,
            idempotency_key="review-ui:second:no-effect",
            task_key="jczq:2026-09-04",
            review_token=intervention.review_token,
            effect={
                "disposition": "no_effect",
                "metric_keys": [],
                "reason": "第二条复盘不改变治理指标。",
            },
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    with OntologyUnitOfWork(fixture.engine) as uow:
        first_disposition = uow.operator_review.current_disposition(first_review_id)
        second_disposition = uow.operator_review.current_disposition(second_review_id)
        first_completion = uow.operator_review.completion_receipt_for_review(first_review_id)
        second_completion = uow.operator_review.completion_receipt_for_review(second_review_id)
    assert completed.status == "completed"
    assert first_disposition is None
    assert first_completion is None
    assert second_disposition is not None
    assert second_disposition.disposition == "no_effect"
    assert second_completion is not None


def test_shadow_terminal_review_reenters_today_after_materialization(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path / "fixture")
    deadline_worker = ConfirmationDeadlineWorker(
        action_service=fixture.action_service,
        protected_tickets=_protected(fixture, tmp_path / "fixture"),
        worker_id="review-ui-deadline",
    )
    assert len(deadline_worker.run_once(limit=10, as_of=fixture.cutoff)) == 1
    _seed_bound_outcome(fixture.engine)
    review_worker = ReviewMaterializationWorker(
        action_service=fixture.action_service,
        review_actions=OperatorReviewActions(
            fixture.action_service,
            shadow_token_signing_key=TOKEN_KEY,
        ),
        worker_id="review-ui-materialization",
        lease_duration=timedelta(minutes=5),
    )
    assert len(
        review_worker.run_once(
            limit=10,
            as_of=fixture.cutoff + timedelta(seconds=1),
        )
    ) == 1
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: fixture.cutoff + timedelta(minutes=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )

    today = queries.today(as_of=fixture.cutoff + timedelta(minutes=1))
    detail = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=fixture.cutoff + timedelta(minutes=1),
    )

    review_entries = [
        entry
        for entry in today.entries
        if entry.kind == "today_work_item_v1" and entry.scope_kind == "review"
    ]
    assert len(review_entries) == 1
    assert detail.active_work_item.scope_kind == "review"
    assert detail.active_work_item.phase == "review"
    assert isinstance(detail.step, ReviewStep)


def test_review_contexts_mint_command_bound_tokens_without_raw_references(
    tmp_path: Path,
) -> None:
    fixture, _review_id = _materialized_review(tmp_path)
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(days=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )

    task = queries.task("jczq:2026-09-04", as_of=AT + timedelta(days=1))
    step = task.step

    assert isinstance(step, ReviewStep)
    assert step.intervention_quality is not None
    assert step.intervention_quality.review_token.startswith("opaque.")
    assert step.intervention_quality.effect_command_token
    dumped = step.model_dump_json()
    assert fixture.fact_id not in dumped
    assert "operator_review_item" not in dumped


def test_real_review_tokens_grade_prediction_and_complete_no_effect_atomically(
    tmp_path: Path,
) -> None:
    fixture, _review_id = _materialized_review(tmp_path)
    action_service = ActionService(lambda: OntologyUnitOfWork(fixture.engine))
    workflow = WorkflowActions(action_service)
    registered = workflow.register_prediction(
        RegisterPredictionRequest(
            match_id=None,
            subject_type="issue",
            subject_id="2026-09-04",
            claim="官方赛果可在截止后取得",
            falsifier="截止后仍无任何正式赛果来源",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="review-ui:prediction",
            requested_at=AT + timedelta(minutes=4),
        )
    )
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    snapshot_tokens = OperatorSnapshotTokenCodec(TOKEN_KEY)
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(days=1),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=snapshot_tokens,
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_text('{"authority":"legacy"}\n', encoding="utf-8")
    actions = OperatorActionService(
        queries=queries,
        action_gateway=SimpleNamespace(),
        workflow_actions=workflow,
        review_actions=fixture.actions,
        snapshot_tokens=snapshot_tokens,
        repository=repository,
        scoreboard_path=scoreboard,
        clock=lambda: AT + timedelta(days=1),
    )

    before = queries.task("jczq:2026-09-04", as_of=AT + timedelta(days=1))
    assert isinstance(before.step, ReviewStep)
    forecast = before.step.forecast_truth[0]
    graded = actions.grade_prediction(
        GradePredictionCommandV2(
            schema_version="2",
            kind="grade_prediction",
            expected_snapshot_token=forecast.grade_command_token,
            idempotency_key="review-ui:grade",
            task_key="jczq:2026-09-04",
            prediction_review_token=forecast.prediction_review_token,
            outcome="hit",
            reason="正式赛果来源已取得。",
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    after_grade = queries.task(
        "jczq:2026-09-04",
        as_of=AT + timedelta(days=1),
    )
    assert graded.status == "completed"
    assert isinstance(after_grade.step, ReviewStep)
    assert after_grade.step.forecast_truth[0].state == "hit"
    intervention = after_grade.step.intervention_quality
    assert intervention is not None

    completed = actions.record_scoreboard_effect_disposition(
        RecordScoreboardEffectDispositionCommandV2(
            schema_version="2",
            kind="record_scoreboard_effect_disposition",
            expected_snapshot_token=intervention.effect_command_token,
            idempotency_key="review-ui:no-effect",
            task_key="jczq:2026-09-04",
            review_token=intervention.review_token,
            effect={
                "disposition": "no_effect",
                "metric_keys": [],
                "reason": "本期仅复盘数据可用性，不改变治理指标。",
            },
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    after_completion = queries.task(
        "jczq:2026-09-04",
        as_of=AT + timedelta(days=1),
    )

    assert registered.status.value == "committed"
    assert completed.status == "completed"
    assert after_completion.selected.state is OperatorTaskState.COMPLETE
    assert after_completion.step.kind == "complete"
