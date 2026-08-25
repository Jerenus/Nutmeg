import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.factor_actions import ApplyFactorStatusRequest
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, FactorInput
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.ticket_actions import LegInput
from nutmeg.ontology.finance.express_flow import ExpressRequest
from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.contracts import ProductActionRequest
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.scoreboard.authority import ScoreboardAuthorityService

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
BELIEF = {"home": 0.65, "draw": 0.2, "away": 0.15}


def _request(
    action_type: str,
    key: str,
    payload: dict[str, object],
    expected_versions: dict[str, int] | None = None,
) -> ProductActionRequest:
    return ProductActionRequest(
        action_type=action_type,
        idempotency_key=key,
        payload=payload,
        expected_versions=expected_versions or {},
    )


def _seed_learning_lifecycle(kernel) -> str:
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.decision.insert_factor_family(FactorFamilyRow("ff-rest", "rest", None))
        uow.decision.insert_factor_definition(
            FactorDefinitionRow(
                factor_definition_id="fd-rest",
                factor_family_id="ff-rest",
                version=1,
                name="rest edge",
                definition=None,
                scope=None,
                status="probation",
                born_from_refs=[],
                valid_from=AT.isoformat(),
                valid_to=None,
                policy_version="governance-v1",
            )
        )
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )

    revision_ids = []
    for index in range(3):
        match_id = f"match-{index}"
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.identity.insert_match_minimal(match_id)
        forecast = kernel.forecast_actions.commit_forecast(
            CommitForecastRequest(
                match_id=match_id,
                market_definition_id="md-had",
                decision_session_id=None,
                prior_distribution=PRIOR,
                belief_distribution=BELIEF,
                factors=[
                    FactorInput(
                        "fd-rest",
                        {"home": 0.15, "draw": -0.1, "away": -0.05},
                        [],
                        [],
                        None,
                    )
                ],
                commitment_tier="commit",
                evidence_bundle_id=None,
                prior_snapshot_id=None,
                falsifier=None,
                actor_id="operator:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"m5:e2e:forecast:{index}",
                requested_at=AT,
            )
        )
        revision_ids.append(forecast.result_refs[0].object_id)
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.market.insert_snapshot(
                SnapshotRow(
                    market_snapshot_id=f"closing-{index}",
                    match_id=match_id,
                    market_definition_id="md-had",
                    snapshot_kind="closing",
                    as_of=AT.isoformat(),
                    fair_distribution={"home": 0.66, "draw": 0.19, "away": 0.15},
                    devig_method="proportional",
                    method_version="v1",
                    source_coverage={},
                    freshness={},
                    disagreement={},
                )
            )

    placed = kernel.express.approve_for_match(
        ExpressRequest(
            channel="jczq",
            account_id="acct-jczq",
            decision_session_id=None,
            legs=[
                LegInput(
                    match_id="match-0",
                    market_definition_id="md-had",
                    selection_id="sel-had-home",
                    forecast_revision_id=revision_ids[0],
                    bucket="main",
                    stake=100.0,
                    entry_odds=2.1,
                )
            ],
            actor_id="operator:owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:e2e:ticket",
            requested_at=AT,
        )
    )
    for index in range(3):
        kernel.reconcile.settle_match(
            ReconcileRequest(
                match_id=f"match-{index}",
                account_id="acct-jczq",
                score_90="2-0",
                status="final",
                source_artifact_retrieval_ids=[],
                actor_id="system:reconcile",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"m5:e2e:reconcile:{index}",
                requested_at=AT,
            )
        )
    return placed.ticket_id


def test_m5_isolated_settlement_learning_authority_lifecycle(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    ticket_id = _seed_learning_lifecycle(kernel)
    build = kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(), built_at="2026-08-24T10:05:00+00:00"
        )
    )
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    queries = ProductQueryService(repository, kernel)
    actions = ProductActionGateway(kernel, repository, clock=lambda: AT)

    review = queries.review(as_of=AT)
    calibration = queries.calibration(as_of=AT)
    assert review.settlements[0].ticket_id == ticket_id
    assert {review.forecast.plane, review.money.plane, review.intervention.plane} == {
        "forecast",
        "money",
        "intervention",
    }
    proposal = next(
        item
        for item in calibration.lifecycle_proposals
        if item.factor_definition_id == "fd-rest"
    )

    adjudication = actions.execute(
        _request(
            "record_adjudication",
            "m5:e2e:factor-adjudication",
            {
                "subject_type": "factor_definition",
                "subject_id": "fd-rest",
                "decision": "apply",
                "reason": "registered interval and sample satisfy lifecycle-v1",
                "evidence_rejected": [],
                "alternative": {"proposal_id": proposal.proposal_id},
            },
        )
    )
    adjudication_id = adjudication.result_refs[0].object_id
    applied = actions.execute(
        _request(
            "apply_factor_status",
            "m5:e2e:factor-apply",
            {
                "proposal_id": proposal.proposal_id,
                "factor_definition_id": "fd-rest",
                "expected_current_status": "probation",
                "target_status": "active",
                "adjudication_id": adjudication_id,
            },
            {"factor_definition:fd-rest": 1},
        )
    )
    assert applied.status == "committed"

    denied = kernel.factor_actions.apply_factor_status(
        ApplyFactorStatusRequest(
            factor_definition_id="fd-rest",
            target_status="retired",
            actor_id="model:analyst",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="m5:e2e:ai-denied",
            requested_at=AT,
            expected_current_status="active",
            expected_factor_version=1,
            adjudication_id=adjudication_id,
        )
    )
    assert denied.status is ActionStatus.REJECTED

    observed = actions.execute(
        _request(
            "record_scoreboard_observation",
            "m5:e2e:manual-observation",
            {
                "group_key": "chains",
                "metric_key": "main",
                "tally": "1/1",
                "detail": "formal operator review",
                "status": "active",
                "numerator": 1,
                "denominator": 1,
                "value": 1,
                "unit": "ratio",
                "evidence_refs": [
                    {"object_type": "adjudication", "object_id": adjudication_id}
                ],
                "effective_at": AT.isoformat(),
                "supersedes_observation_id": None,
            },
        )
    )
    assert observed.status == "committed"
    rebuild = kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(), built_at="2026-08-24T10:10:00+00:00"
        )
    )
    assert rebuild.high_watermark > build.high_watermark

    legacy = tmp_path / "legacy-scoreboard.json"
    legacy.write_text(
        '{"updated_at":"2026-08-24T09:00:00Z","chains":{"main":1}}\n',
        encoding="utf-8",
    )
    legacy_hash = hashlib.sha256(legacy.read_bytes()).hexdigest()
    authority = ScoreboardAuthorityService(kernel)
    shadow = authority.shadow(
        legacy_path=legacy,
        classification=[
            {
                "group_key": "chains",
                "metric_key": "main",
                "classification": "formal_manual",
                "target_ref": "scoreboard_observation:chains:main",
            }
        ],
        projection_version="sb-v1",
        source_high_watermark=rebuild.high_watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    review_id = shadow.result_refs[0].object_id
    sop_root = tmp_path / "sop"
    shutil.copytree(Path("tests/fixtures/m5/sop"), sop_root)
    cutover = authority.cutover(
        legacy_path=legacy,
        shadow_review_id=review_id,
        expected_authority_version=1,
        sop_paths=list(sop_root.iterdir()),
        approve=True,
        requested_at=AT,
    )
    assert cutover.status is ActionStatus.COMMITTED
    exported = authority.export(tmp_path / "compatibility.json", requested_at=AT)
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == legacy_hash
    assert exported.path.is_file()
    document = json.loads(exported.path.read_text(encoding="utf-8"))
    assert document["authority"]["state"] == "ontology"

    factor = queries.ontology_object("factor_definition", "fd-rest", as_of=AT)
    assert factor.properties["status"] == "active"
    assert any(item.action_type == "apply_factor_status" for item in factor.actions)
    assert queries.scoreboard(as_of=AT).authority.state == "ontology"
