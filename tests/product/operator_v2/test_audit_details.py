from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product import operator_contracts, operator_queries
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_contracts import (
    JudgeMatchesStep,
    OperatorLane,
    OperatorTaskState,
    OperatorTaskSummary,
    TaskProgressSummary,
)
from nutmeg.product.operator_lanes import SaleOfferSnapshot, SaleSlateSnapshot
from nutmeg.product.operator_queries import OperatorQueryService, _BuiltTask
from nutmeg.product.operator_runtime import validate_operator_runtime
from nutmeg.product.operator_state import OperatorTaskFacts, resolve_state
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.repository import MatchReadRow

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
COMMIT = "b" * 40
SIGNING_KEY = "operator-audit-detail-signing-key-32-bytes"
TASK_HASH = "a" * 64
SLATE_HASH = "c" * 64


class _Repository:
    def __init__(self, slate: SaleSlateSnapshot) -> None:
        self.slate = slate

    def operator_sale_slates(self, *, as_of: str) -> tuple[SaleSlateSnapshot, ...]:
        del as_of
        return (self.slate,)

    def operator_schedule_checks(self, *, as_of: str) -> tuple[()]:
        del as_of
        return ()

    def match(self, match_id: str, as_of: str) -> MatchReadRow:
        del as_of
        return MatchReadRow(
            match_id=match_id,
            match_revision_id="revision-1",
            scheduled_at=NOW + timedelta(hours=1),
            status="scheduled",
            schedule_status="confirmed",
            home_team="主队",
            away_team="客队",
            home_team_id="home-1",
            away_team_id="away-1",
            home_resolution_status="resolved",
            away_resolution_status="resolved",
            competition_id="competition-test",
            competition_edition_id="edition-test",
            competition="测试联赛",
            round_label=None,
            venue_id=None,
        )

    def action_high_watermark(self) -> int:
        return 17

    def scoreboard_projection(self, *, as_of: str) -> dict[str, object]:
        del as_of
        return {
            "health": {
                "state": "stale",
                "projection_version": "scoreboard-v3",
                "source_high_watermark": 12,
                "built_at": (NOW - timedelta(minutes=5)).isoformat(),
            },
            "rows": [],
        }


def _slate() -> SaleSlateSnapshot:
    return SaleSlateSnapshot(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        slate_revision_id="slate-revision-internal-3",
        content_hash=SLATE_HASH,
        offers=(
            SaleOfferSnapshot(
                official_offer_family_id="offer-family-internal-1",
                official_offer_revision_id="offer-revision-internal-9",
                match_id="match-internal-1",
                official_match_no="001",
                market_definition_ids=("md-had",),
                sale_opens_at=NOW - timedelta(hours=1),
                sale_deadline_at=NOW + timedelta(hours=2),
                source_status="on_sale",
            ),
        ),
        source_official=True,
        revision_no=3,
        published_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(minutes=5),
    )


def _built() -> _BuiltTask:
    facts = OperatorTaskFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        deadline_at=NOW + timedelta(hours=2),
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=1,
        candidate_count=0,
        selected_candidate_id=None,
        audit_recorded=False,
        deployment_decision=None,
        ticket_artifact_id=None,
        confirmation_state=None,
        placement_state=None,
        result_available=False,
        pending_review_items=0,
    )
    task_id = "zucai:26116"
    state = resolve_state(facts)
    return _BuiltTask(
        facts=facts,
        summary=OperatorTaskSummary(
            task_id=task_id,
            lane=OperatorLane.ZUCAI,
            business_key="26116",
            title="胜负彩 26116 期",
            state=state,
            deadline_at=facts.deadline_at,
            waiting_until=None,
            is_actionable=state is not OperatorTaskState.COMPLETE,
            next_action_label="继续逐场裁决",
            priority_rank=0,
        ),
        progress=TaskProgressSummary(completed=2, total=14, label="逐场判断"),
        step=JudgeMatchesStep(
            task_id=task_id,
            item_key="judgment-prescription",
            title="审计测试",
            prompt="",
            options=[],
            mode="prescription_ready",
            completed_match_count=2,
            required_match_count=14,
            prescription_command_token="opaque-prescription-command",
            judgment_revision_tokens=["opaque-judgment-revision"],
        ),
        mutation_token=TASK_HASH,
    )


def _query_service() -> OperatorQueryService:
    queries = OperatorQueryService(
        repository=_Repository(_slate()),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
        snapshot_tokens=OperatorSnapshotTokenCodec(SIGNING_KEY),
    )
    queries._build_all = lambda _cutoff: [_built()]  # type: ignore[method-assign]
    return queries


def test_audit_envelope_contract_is_strict_and_carries_only_typed_technical_data() -> None:
    envelope_type = getattr(operator_contracts, "OperatorAuditEnvelopeV1", None)
    lineage_type = getattr(operator_contracts, "OperatorAuditLineageItemV1", None)
    projection_type = getattr(operator_contracts, "OperatorAuditProjectionV1", None)
    assert envelope_type is not None
    assert lineage_type is not None
    assert projection_type is not None

    lineage = lineage_type(
        relation="uses",
        object_type="official_sale_slate_revision",
        object_id="slate-revision-internal-3",
        revision_id="slate-revision-internal-3",
        content_hash=SLATE_HASH,
        created_by_action_id="action-internal-4",
        source_payload_location="artifacts/schedules/26116.json",
    )
    projection = projection_type(
        projection_name="scoreboard",
        state="stale",
        projection_version="scoreboard-v3",
        source_action_high_watermark=12,
        current_action_high_watermark=17,
        built_at=NOW,
    )
    envelope = envelope_type(
        as_of=NOW,
        title="胜负彩 26116 期技术审计",
        task_label="胜负彩 26116 期",
        work_item_label="本期 14 场",
        return_href="/operator-next/zucai/26116/sale-wave-opaque0001",
        task_id="zucai:26116",
        work_item_id="zucai:26116:work-item-internal",
        task_snapshot_hash=TASK_HASH,
        lineage=[lineage],
        projection=projection,
    )

    assert envelope.kind == "operator_audit_envelope_v1"
    payload = envelope.model_dump(mode="python")
    payload["raw_json"] = {"secret": "not allowed"}
    with pytest.raises(ValidationError):
        envelope_type.model_validate(payload)
    with pytest.raises(ValidationError):
        projection_type(
            **{
                **projection.model_dump(mode="python"),
                "current_action_high_watermark": 17.0,
            }
        )
    with pytest.raises(ValidationError):
        envelope_type(
            **{
                **envelope.model_dump(mode="python"),
                "as_of": datetime(2026, 9, 5, 8),
            }
        )


def test_audit_token_resolver_rejects_tampering_and_non_audit_tokens() -> None:
    resolver_type = getattr(operator_queries, "OperatorAuditTokenResolver", None)
    assert resolver_type is not None
    codec = OperatorSnapshotTokenCodec(SIGNING_KEY)
    resolver = resolver_type(codec)
    token = resolver.issue(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        work_item_key="sale-wave-opaque0001",
        task_snapshot_hash=TASK_HASH,
    )

    assert "26116" not in token
    locator = resolver.resolve(token)
    assert locator.lane is OperatorLane.ZUCAI
    assert locator.business_key == "26116"
    assert locator.work_item_key == "sale-wave-opaque0001"
    assert locator.task_snapshot_hash == TASK_HASH

    replacement = "A" if token[-1] != "A" else "B"
    with pytest.raises(ProductNotFoundError, match="audit record not found"):
        resolver.resolve(token[:-1] + replacement)
    with pytest.raises(ProductNotFoundError, match="audit record not found"):
        resolver.resolve("not-a-signed-token")


def test_query_issues_audit_link_and_resolves_current_lineage_and_watermarks() -> None:
    queries = _query_service()

    detail = queries.task_v2(OperatorLane.ZUCAI, "26116", as_of=NOW)
    assert detail.active_work_item.audit_href is not None
    prefix = "/operator-next/audit/"
    assert detail.active_work_item.audit_href.startswith(prefix)
    token = detail.active_work_item.audit_href.removeprefix(prefix)

    envelope = queries.audit(token, as_of=NOW)

    assert envelope.task_id == "zucai:26116"
    assert envelope.task_snapshot_hash == TASK_HASH
    assert envelope.projection.state == "stale"
    assert envelope.projection.source_action_high_watermark == 12
    assert envelope.projection.current_action_high_watermark == 17
    assert [item.object_type for item in envelope.lineage] == [
        "operator_work_item",
        "official_sale_slate_revision",
        "official_offer_revision",
    ]
    assert envelope.lineage[1].content_hash == SLATE_HASH

    resolver = operator_queries.OperatorAuditTokenResolver(
        OperatorSnapshotTokenCodec(SIGNING_KEY)
    )
    unknown = resolver.issue(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        work_item_key="sale-wave-doesnotexist",
        task_snapshot_hash=TASK_HASH,
    )
    with pytest.raises(ProductNotFoundError, match="audit record not found"):
        queries.audit(unknown, as_of=NOW)


class _NoCalls:
    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected service call: {name}")


class _AuditPageQueries:
    def __init__(self, envelope) -> None:
        self.envelope = envelope
        self.calls: list[tuple[object, ...]] = []

    def audit(self, token: str, *, as_of: datetime):
        self.calls.append(("audit", token, as_of))
        if token == "unknown-token":
            raise ProductNotFoundError("operator audit record not found")
        return self.envelope

    def lane(self, lane: OperatorLane, *, as_of: datetime):
        self.calls.append(("lane", lane, as_of))
        raise AssertionError("the explicit audit route must win over the lane route")

    def worklist(self, *, as_of: datetime):
        return SimpleNamespace(as_of=as_of, selected=None, tasks=[])


def _audit_page_client(tmp_path: Path) -> tuple[TestClient, _AuditPageQueries]:
    envelope_type = getattr(operator_contracts, "OperatorAuditEnvelopeV1", None)
    lineage_type = getattr(operator_contracts, "OperatorAuditLineageItemV1", None)
    projection_type = getattr(operator_contracts, "OperatorAuditProjectionV1", None)
    assert envelope_type is not None
    assert lineage_type is not None
    assert projection_type is not None
    envelope = envelope_type(
        as_of=NOW,
        title="审计 <script>alert(1)</script>",
        task_label="胜负彩 26116 期",
        work_item_label="本期 14 场",
        return_href="/operator-next/zucai/26116/sale-wave-opaque0001",
        task_id="zucai:26116",
        work_item_id="work-item-<internal>",
        task_snapshot_hash=TASK_HASH,
        audit_override_ticket_batch_token="opaque-current-ticket-batch-token",
        lineage=[
            lineage_type(
                relation="uses",
                object_type="official_sale_slate_revision",
                object_id="slate-<internal>",
                revision_id=None,
                content_hash=SLATE_HASH,
                created_by_action_id=None,
                source_payload_location=None,
            )
        ],
        projection=projection_type(
            projection_name="scoreboard",
            state="ready",
            projection_version="scoreboard-v3",
            source_action_high_watermark=17,
            current_action_high_watermark=17,
            built_at=NOW,
        ),
    )
    queries = _AuditPageQueries(envelope)
    production = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=production,
        production_data_dir=production,
        operator_runtime_scope="production",
        operator_surface_mode="shadow",
        candidate_commit=COMMIT,
    )
    runtime = validate_operator_runtime(
        settings,
        running_commit=COMMIT,
        dirty=False,
        data_dir_was_explicit=False,
    )
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
        session_secret="audit-page-session",
        csrf_secret="audit-page-csrf",
        clock=lambda: NOW,
    )
    return TestClient(app), queries


def test_explicit_audit_route_renders_escaped_technical_details(tmp_path: Path) -> None:
    client, queries = _audit_page_client(tmp_path)

    response = client.get("/operator-next/audit/signed-opaque-token")

    assert response.status_code == 200
    assert [call[0] for call in queries.calls] == ["audit"]
    assert "技术审计" in response.text
    assert "zucai:26116" in response.text
    assert "work-item-&lt;internal&gt;" in response.text
    assert "审计 &lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "signed-opaque-token" not in response.text
    assert "opaque-current-ticket-batch-token" in response.text
    assert "--ticket-batch-token" in response.text
    assert "--user-override" in response.text
    assert "<pre" not in response.text
    assert "schema_version" not in response.text


def test_unknown_audit_token_is_a_generic_not_found(tmp_path: Path) -> None:
    client, queries = _audit_page_client(tmp_path)

    response = client.get("/operator-next/audit/unknown-token")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "object_not_found"
    assert body["message"] == "operator audit record not found"
    assert body["retryable"] is False
    assert body["details"] == {}
    assert [call[0] for call in queries.calls] == ["audit"]
