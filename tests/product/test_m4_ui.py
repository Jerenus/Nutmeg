import re
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.contracts import (
    TicketArtifactDetail,
    TicketAuditFindingSummary,
    TicketBatchHistoryResponse,
    TicketBatchRevisionSummary,
    TicketLegCommand,
    TicketSelection,
    TicketWorkbenchMatch,
    TicketWorkbenchResponse,
)

from .conftest import CLOCK


def _leg() -> TicketLegCommand:
    return TicketLegCommand(
        leg_key="match-1:md-had:home",
        match_id="match-1",
        match_no=1,
        name='<script>alert("leg")</script>',
        market_definition_id="md-had",
        selection_id="sel-had-home",
        outcome_key="home",
        faces="31",
        forecast_revision_id="fr-current",
        entry_quote_id="quote-home",
        odds=2.1,
        line=None,
        bucket="main",
        fair={"home": 0.6, "draw": 0.25, "away": 0.15},
        confidence=4,
        directional_flags=[],
        nondirectional_flags=["two_way_instability"],
        anchor_integrity="pass",
        precedents=[],
    )


def _batch(
    batch_id: str,
    revision_no: int,
    state: str,
    audit_state: str,
    *,
    artifact_ids: list[str] | None = None,
    finding: TicketAuditFindingSummary | None = None,
    legs: list[TicketLegCommand] | None = None,
) -> TicketBatchRevisionSummary:
    return TicketBatchRevisionSummary(
        ticket_batch_revision_id=f"revision-{batch_id}-{revision_no}",
        ticket_batch_id=batch_id,
        revision_no=revision_no,
        supersedes_revision_id=(
            f"revision-{batch_id}-{revision_no - 1}" if revision_no > 1 else None
        ),
        run_date=date(2026, 8, 24),
        channel="jczq",
        account_id="acct-jczq",
        currency="CNY",
        deadline_at="2026-08-24T12:00:00+00:00",
        state=state,
        content_hash=(batch_id[-1] * 64),
        source_artifact_id=f"sha256:{batch_id[-1] * 64}",
        created_at="2026-08-24T10:00:00+00:00",
        created_by_action_id=f"action-{batch_id}-{revision_no}",
        legs=legs if legs is not None else [_leg()],
        composition={
            "total_stake_yuan": 100 if state not in {"empty", "approved_empty"} else 0,
            "n_tickets": 1 if state not in {"empty", "approved_empty"} else 0,
            "tickets": (
                [
                    {
                        "structure": "single",
                        "n_legs": 1,
                        "stake_yuan": 100,
                        "computed_hit_prob": 0.55,
                    }
                ]
                if state not in {"empty", "approved_empty"}
                else []
            ),
        },
        audit_state=audit_state,
        audit_findings=[finding] if finding is not None else [],
        artifact_ids=artifact_ids or [],
        added_leg_keys=["match-1:md-had:home"] if revision_no == 1 else [],
        removed_leg_keys=[],
        changed_leg_keys=[],
    )


class _TicketQueries:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        warning = TicketAuditFindingSummary(
            finding_id="finding-warn-1",
            level="WARN",
            code="modal_stack_mismatch",
            match_no=1,
            message='<img src=x onerror=alert("finding")>',
            since="26103",
        )
        error = TicketAuditFindingSummary(
            finding_id="finding-error-1",
            level="ERROR",
            code="directional_flag_single",
            match_no=1,
            message="方向性旗场次不可裸单",
            since="26098",
        )
        self.warn_first = _batch("batch-w", 1, "draft", "warn", finding=warning)
        self.warn_current = _batch(
            "batch-w", 2, "draft", "warn", finding=warning
        )
        self.error_current = _batch(
            "batch-e", 1, "draft", "error", finding=error
        )
        self.approved = _batch(
            "batch-a",
            2,
            "approved",
            "clean",
            artifact_ids=["artifact-1"],
        )
        self.empty = _batch(
            "batch-0", 3, "approved_empty", "clean", legs=[]
        )
        self.workbench = TicketWorkbenchResponse(
            date=date(2026, 8, 24),
            as_of=CLOCK,
            matches=[
                TicketWorkbenchMatch(
                    match_id="match-1",
                    match_revision_id="match-revision-1",
                    match_no=1,
                    home_team='<script>alert("team")</script>',
                    away_team="Away FC",
                    competition="Fixture League",
                    kickoff_at="2026-08-24T12:00:00+00:00",
                    market_definition_id="md-had",
                    forecast_revision_id="fr-current",
                    forecast_revision_no=2,
                    belief_distribution={
                        "home": 0.6,
                        "draw": 0.25,
                        "away": 0.15,
                    },
                    selections=[
                        TicketSelection(
                            market_definition_id="md-had",
                            selection_id="sel-had-home",
                            outcome_key="home",
                            quote_id="quote-home",
                            odds=2.1,
                            captured_at="2026-08-24T09:55:00+00:00",
                            provider="sporttery",
                            eligible=True,
                        ),
                        TicketSelection(
                            market_definition_id="md-had",
                            selection_id="sel-had-draw",
                            outcome_key="draw",
                            eligible=False,
                            block_reasons=["no_active_quote"],
                        ),
                    ],
                    eligible=True,
                )
            ],
            batch_revisions=[
                self.warn_current,
                self.error_current,
                self.approved,
                self.empty,
            ],
        )
        self.artifact = TicketArtifactDetail(
            ticket_artifact_id="artifact-1",
            ticket_batch_revision_id=self.approved.ticket_batch_revision_id,
            ticket_index=0,
            ticket_hash="a" * 64,
            source_artifact_id=f"sha256:{'a' * 64}",
            amount=100.0,
            currency="CNY",
            channel="jczq",
            deadline_at="2026-08-24T12:00:00+00:00",
            payload={"account_id": "acct-jczq"},
            approved_at="2026-08-24T10:00:00+00:00",
            approved_by_action_id="action-approve",
            confirmation_state="not_issued",
            placement_state="unplaced",
        )

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def ticket_workbench(self, day: date, *, as_of):
        assert day == date(2026, 8, 24)
        assert as_of == CLOCK
        return self.workbench

    def ticket_batch(self, ticket_batch_id: str) -> TicketBatchHistoryResponse:
        if ticket_batch_id == "batch-w":
            revisions = [self.warn_first, self.warn_current]
        else:
            current = next(
                item
                for item in self.workbench.batch_revisions
                if item.ticket_batch_id == ticket_batch_id
            )
            revisions = [current]
        return TicketBatchHistoryResponse(
            ticket_batch_id=ticket_batch_id, revisions=revisions
        )

    def ticket_artifact(self, ticket_artifact_id: str, *, as_of=None):
        assert ticket_artifact_id == "artifact-1"
        return self.artifact


@pytest.fixture
def client(m3_product_services) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=_TicketQueries(m3_product_services.queries),
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
        tickets=object(),
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m4-ui-session-secret",
            csrf_secret="m4-ui-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def test_ticket_workbench_renders_matrix_audit_revisions_and_confirmation(
    client: TestClient,
) -> None:
    response = client.get(
        "/tickets?date=2026-08-24&as_of=2026-08-24T10:00:00Z"
    )

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="ticket-workbench"' in html
    assert 'data-ticket-face-matrix="true"' in html
    assert "fr-current" in html
    assert "quote-home" in html
    assert "2.100" in html
    assert "审计账页" in html
    assert "Revision Rail" in html
    assert "finding-warn-1" in html
    assert "a" * 64 in html
    assert 'data-action="issue-ticket-confirmation"' in html
    assert 'data-action="confirm-ticket-placement"' in html
    assert "批准空仓" in html
    assert 'aria-live="polite"' in html
    assert 'data-composition-summary="true"' in html
    assert "票数" in html and "1 张" in html
    assert "总额" in html and "100 元" in html
    assert "结构" in html and "single" in html
    assert "组合覆盖" in html and "1 腿" in html


def test_ticket_workbench_escapes_untrusted_content_and_keeps_error_blocked(
    client: TestClient,
) -> None:
    html = client.get("/tickets?date=2026-08-24").text

    assert '<script>alert("team")</script>' not in html
    assert '<script>alert("leg")</script>' not in html
    assert '<img src=x onerror=alert("finding")>' not in html
    assert "&lt;script&gt;" in html
    error_panel = html.split('data-ticket-batch="batch-e"', 1)[1].split(
        "</article>", 1
    )[0]
    assert "ERROR / 不可覆盖" in error_panel
    assert 'data-action="approve-ticket-batch"' not in error_panel


def test_warn_adjudication_is_explicit_and_actor_never_enters_forms(
    client: TestClient,
) -> None:
    html = client.get("/tickets?date=2026-08-24").text

    assert 'data-action="ticket-warn-adjudication"' in html
    assert 'name="reason"' in html
    assert 'name="evidence_rejected"' in html
    assert 'name="no_evidence_rejected"' in html
    assert "明确确认没有拒绝任何证据" in html
    assert 'name="actor_role"' not in html
    assert 'name="actor_id"' not in html
    assert 'class="skip-link" href="#main-content"' in html
    assert 'aria-label="票据工作台主导航"' in html


def test_ticket_javascript_only_collects_forms_and_calls_m4_endpoints(
    client: TestClient,
) -> None:
    script = client.get("/assets/product/app.js").text

    for route in (
        "/api/v1/ticket-batches",
        "/remove-leg",
        "/approve",
        "/confirmations",
        "/confirm",
    ):
        assert route in script
    assert "FileReader" in script
    assert "crypto.randomUUID()" in script
    assert "receipt_base64" in script
    for forbidden in (
        "compose_tickets",
        "audit_legs",
        "devig",
        "budget allocation",
        "combined_odds",
        "hash generation",
        "expiry validation",
        "payout",
        "settlement",
        "stake *",
        "odds *",
    ):
        assert forbidden.casefold() not in script.casefold()


def test_ticket_styles_have_sticky_ledger_narrow_cards_and_touch_targets(
    client: TestClient,
) -> None:
    css = client.get("/assets/product/app.css").text

    assert re.search(
        r"\.ticket-workbench-grid\s*\{[^}]*grid-template-columns:",
        css,
        re.DOTALL,
    )
    assert re.search(
        r"\.ticket-audit-ledger\s*\{[^}]*position:\s*sticky;",
        css,
        re.DOTALL,
    )
    narrow = css.split("@media (max-width: 760px)", maxsplit=1)[1]
    assert re.search(
        r"\.ticket-workbench-grid[^\{]*\{[^}]*grid-template-columns:\s*1fr;",
        narrow,
        re.DOTALL,
    )
    assert ".ticket-match-card" in narrow
    assert "min-height: 44px" in narrow
    assert "overflow-wrap: anywhere" in css
