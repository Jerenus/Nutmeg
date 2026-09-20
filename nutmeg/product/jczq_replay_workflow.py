"""Replay-only JCZQ A4-A6 orchestration through existing governed Actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import insert

from nutmeg.ontology.actions.bundle_actions import BundleActions
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.actions.outcome_actions import OutcomeActions, RecordOutcomeRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RegisterPredictionRequest,
    WorkflowActions,
)
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FacePrecedentInput,
    FaceProbabilityInput,
    FreezeJudgmentPrescriptionRequest,
    OperatorDecisionActions,
    RecordBaselineEnvelopeRequest,
    RecordNoTicketRequest,
    RequestCandidateGenerationRequest,
)
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    EvidenceFreezeGate,
    EvidenceFreezeMatchPlan,
    RequestEvidenceFreezeRequest,
)
from nutmeg.ontology.operator.result_actions import OperatorResultActions
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository.artifacts import ArtifactRetrievalRow
from nutmeg.ontology.repository.market import QuoteRow, SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_board_workflow import JczqBoard, JczqBoardMatch
from nutmeg.product.jczq_replay_inputs import ReplayInputManifest
from nutmeg.product.operator_workers import (
    CandidateGenerationWorker,
    EvidenceFreezeRequestWorker,
    MarketBaselineWorker,
)


def _stable_id(kind: str, *parts: object) -> str:
    material = canonical_json([kind, *parts])
    return f"{kind}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReplayWorkflowResult:
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    candidate_generation_request_id: str
    no_ticket_revision_id: str


@dataclass(frozen=True, slots=True)
class ReplayResultSummary:
    authoritative_result_count: int
    replay_prediction_count: int
    replay_score_count: int
    rsi_statuses: dict[str, str]
    gaps: tuple[str, ...]


def _load_reads(day_root: Path) -> tuple[dict[str, object], ...]:
    document = json.loads((day_root / "reads.json").read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError("historical replay Reads must be a list")
    if any(not isinstance(item, dict) for item in document):
        raise ValueError("historical replay Read must be an object")
    return tuple(document)


def _select_match(
    board: JczqBoard,
    reads: tuple[dict[str, object], ...],
    observation_ids: dict[str, str],
) -> tuple[JczqBoardMatch, datetime]:
    read_times: dict[str, datetime] = {}
    board_ids = {match.match_id for match in board.matches}
    for index, read in enumerate(reads):
        supplied_match_id = str(read.get("match_id") or "")
        match_id = (
            supplied_match_id
            if supplied_match_id in board_ids
            else board.matches[index].match_id
        )
        made_at = datetime.fromisoformat(str(read["made_at"]))
        if made_at.tzinfo is None or made_at.utcoffset() is None:
            raise ValueError("historical replay Read time must be timezone-aware")
        read_times[match_id] = made_at
    eligible = tuple(
        (match, read_times[match.match_id])
        for match in board.matches
        if match.match_id in observation_ids
        and match.match_id in read_times
        and read_times[match.match_id] + timedelta(minutes=1) < match.kickoff_at
    )
    if not eligible:
        raise ValueError("historical replay has no pre-kickoff researched match for A4-A6")
    return max(eligible, key=lambda item: item[0].kickoff_at)


def _seed_official_market(
    kernel,
    *,
    replay_run_id: str,
    day: str,
    day_root: Path,
    manifest: ReplayInputManifest,
    match: JczqBoardMatch,
    market_time: datetime,
) -> tuple[str, str, tuple[str, ...]]:
    source_run_id = _stable_id("replay-sale-source", replay_run_id)
    artifact_id = _stable_id(
        "replay-artifact", manifest.entry("sporttery_markets.json").sha256
    )
    retrieval_id = _stable_id("replay-sale-retrieval", replay_run_id)
    slate_id = _stable_id("replay-slate", replay_run_id)
    offer_family_id = _stable_id("replay-offer-family", replay_run_id, match.match_id)
    offer_id = _stable_id("replay-offer", replay_run_id, match.match_id)
    snapshot_id = _stable_id("replay-operator-snapshot", replay_run_id, match.match_id)
    board_path = day_root / "sporttery_markets.json"
    board_bytes = board_path.read_bytes()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.connection.execute(
            insert(schema.source_runs).prefix_with("OR IGNORE").values(
                source_run_id=source_run_id,
                source_name="sporttery_historical_replay",
                source_type="official_sale_schedule",
                started_at=market_time.isoformat(),
                finished_at=market_time.isoformat(),
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        uow.connection.execute(
            insert(schema.source_artifacts).prefix_with("OR IGNORE").values(
                artifact_id=artifact_id,
                first_recorded_at=market_time.isoformat(),
                content_type="application/json",
                storage_path=str(board_path),
                byte_size=len(board_bytes),
                content_hash=manifest.entry("sporttery_markets.json").sha256,
            )
        )
        uow.artifacts.insert_retrieval(
            ArtifactRetrievalRow(
                artifact_retrieval_id=retrieval_id,
                artifact_id=artifact_id,
                source_run_id=source_run_id,
                source_name="sporttery_historical_replay",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url=None,
                requested_url=None,
                published_at=market_time.isoformat(),
                retrieved_at=market_time.isoformat(),
                status="stored",
            )
        )
        uow.connection.execute(
            insert(sos.official_sale_slate_revisions).values(
                slate_revision_id=slate_id,
                slate_family_id=f"jczq:{day}",
                lane="jczq",
                business_key=day,
                revision_no=1,
                source_artifact_retrieval_id=retrieval_id,
                published_at=market_time.isoformat(),
                retrieved_at=market_time.isoformat(),
                valid_from=market_time.isoformat(),
                supersedes_slate_revision_id=None,
                content_hash=_hash({"day": day, "match_id": match.match_id}),
            )
        )
        uow.connection.execute(
            insert(sos.official_offer_families).values(
                official_offer_family_id=offer_family_id,
                lane="jczq",
                business_key=day,
                official_match_no=match.official_match_no,
                match_id=match.match_id,
                created_at=market_time.isoformat(),
            )
        )
        uow.connection.execute(
            insert(sos.official_offer_revisions).values(
                official_offer_revision_id=offer_id,
                official_offer_family_id=offer_family_id,
                slate_revision_id=slate_id,
                match_id=match.match_id,
                official_match_no=match.official_match_no,
                market_definition_ids_json=canonical_json(["md-had"]),
                sale_opens_at=market_time.isoformat(),
                sale_deadline_at=match.kickoff_at.isoformat(),
                status="on_sale",
            )
        )
        quote_ids = tuple(
            _stable_id("replay-quote", replay_run_id, match.match_id, face)
            for face in ("3", "1", "0")
        )
        for quote_id, selection_id, odds in zip(
            quote_ids,
            ("sel-had-home", "sel-had-draw", "sel-had-away"),
            (2.5, 10 / 3, 10 / 3),
            strict=True,
        ):
            uow.market.insert_quote(
                QuoteRow(
                    quote_id=quote_id,
                    match_id=match.match_id,
                    market_definition_id="md-had",
                    selection_id=selection_id,
                    provider="sporttery",
                    bookmaker=None,
                    decimal_odds=odds,
                    captured_at=market_time.isoformat(),
                    artifact_retrieval_id=retrieval_id,
                    quote_status="active",
                )
            )
        uow.market.insert_snapshot(
            SnapshotRow(
                market_snapshot_id=snapshot_id,
                match_id=match.match_id,
                market_definition_id="md-had",
                snapshot_kind="historical_replay_operator_cutoff",
                as_of=market_time.isoformat(),
                fair_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                devig_method="proportional",
                method_version="1",
                source_coverage={"manifest": manifest.manifest_hash},
                freshness={},
                disagreement={},
            ),
            quote_ids=quote_ids,
        )
    return slate_id, offer_id, quote_ids


def run_replay_workflow(
    action_service: ActionService,
    *,
    kernel,
    replay_run_id: str,
    day: str,
    day_root: Path,
    manifest: ReplayInputManifest,
    board: JczqBoard,
    observation_ids: dict[str, str],
) -> ReplayWorkflowResult:
    reads = _load_reads(day_root)
    match, decision_time = _select_match(board, reads, observation_ids)
    market_time_text = manifest.entry("sporttery_markets.json").semantic_timestamp
    if market_time_text is None:
        raise ValueError("official market update time is missing")
    market_time = datetime.fromisoformat(market_time_text.replace(" ", "T"))
    if market_time.tzinfo is None or market_time.utcoffset() is None:
        market_time = market_time.replace(tzinfo=decision_time.tzinfo)
    if market_time >= decision_time:
        raise ValueError("official market update is not before the replay decision")

    slate_id, offer_id, quote_ids = _seed_official_market(
        kernel,
        replay_run_id=replay_run_id,
        day=day,
        day_root=day_root,
        manifest=manifest,
        match=match,
        market_time=market_time,
    )
    snapshot_id = _stable_id("replay-operator-snapshot", replay_run_id, match.match_id)
    observation_id = observation_ids[match.match_id]
    task_family_id = f"jczq:{day}"
    work_item_id = f"{task_family_id}:wave:replay"
    actor_id = f"replay:{replay_run_id}:adjudicator"
    actor_role = ActorRole.REPLAY_ADJUDICATOR
    gate = EvidenceFreezeGate(
        task_family_id=task_family_id,
        lane="jczq",
        business_key=day,
        slate_revision_id=slate_id,
        task_snapshot_hash=_hash({"slate": slate_id, "day": day}),
        requirement_revision_token=_stable_id("replay-requirements", replay_run_id),
        information_cutoff_at=decision_time,
        policy_version="governance-v1",
        ready=True,
        required_match_count=1,
        matches=(
            EvidenceFreezeMatchPlan(
                match_id=match.match_id,
                market_snapshot_id=snapshot_id,
                prior_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                candidate_observation_ids=(observation_id,),
                caveat_claim_ids=(),
                requirement_states=tuple(
                    (requirement, "complete")
                    for requirement in ("E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC")
                ),
                requirement_ref_tokens=(observation_id,),
                market_prior_ref_tokens=(snapshot_id, *quote_ids),
                conflicts_cleared_ref_tokens=(),
            ),
        ),
    )

    def resolve_gate(_uow, _lane: str, _business_key: str, _as_of: datetime):
        return gate

    evidence_actions = EvidenceActions(
        action_service,
        freeze_gate_resolver=resolve_gate,
    )
    freeze = evidence_actions.request_evidence_freeze(
        RequestEvidenceFreezeRequest(
            task_family_id=task_family_id,
            lane="jczq",
            business_key=day,
            requirement_revision_token=gate.requirement_revision_token,
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:request-evidence-freeze",
            requested_at=decision_time,
        )
    )
    frozen = EvidenceFreezeRequestWorker(
        action_service=action_service,
        evidence_actions=evidence_actions,
        bundle_actions=BundleActions(action_service),
        worker_id=f"replay-evidence-{replay_run_id}",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=decision_time + timedelta(seconds=1))
    if not freeze.is_success or len(frozen) != 1:
        raise ValueError("historical replay evidence freeze did not complete")
    task_bundle_id = frozen[0].result_refs[0].object_id

    decision_actions = OperatorDecisionActions(action_service)
    baseline = MarketBaselineWorker(
        action_service=action_service,
        decision_actions=decision_actions,
        worker_id=f"replay-baseline-{replay_run_id}",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: work_item_id,
    ).run_once(limit=1, as_of=decision_time + timedelta(seconds=2))
    if len(baseline) != 1:
        raise ValueError("historical replay market baseline did not complete")
    baseline_id = baseline[0].result_refs[0].object_id

    envelope = decision_actions.record_baseline_envelope(
        RecordBaselineEnvelopeRequest(
            task_evidence_bundle_revision_id=task_bundle_id,
            work_item_id=work_item_id,
            ticket_kind="jczq_pass",
            capital_cap_minor=20_000,
            currency="CNY",
            maximum_ticket_count=2,
            offer_constraints=(
                BaselineEnvelopeOfferConstraint(
                    official_match_no=match.official_match_no,
                    market_code="had",
                    allowed_face_bundles=(
                        FaceBundleInput(bundle_code="home", face_codes=("3",)),
                        FaceBundleInput(bundle_code="home_draw", face_codes=("3", "1")),
                    ),
                    omission_allowed=False,
                ),
            ),
            structure_templates=(
                BaselineEnvelopeStructureTemplate(
                    kind="jczq_pass",
                    structure_code="single-1",
                    eligible_official_match_nos=(match.official_match_no,),
                    pass_size=1,
                    required_offer_count=1,
                    maximum_groups=1,
                ),
            ),
            maximum_exhaustive_candidate_count=100,
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:baseline-envelope",
            requested_at=decision_time + timedelta(seconds=3),
            expected_current_revision_no=0,
        )
    )
    envelope_id = envelope.result_refs[0].object_id
    prior = (
        FaceProbabilityInput("3", "0.400000000000"),
        FaceProbabilityInput("1", "0.300000000000"),
        FaceProbabilityInput("0", "0.300000000000"),
    )
    judgment = decision_actions.commit_operator_match_judgment(
        CommitOperatorMatchJudgmentRequest(
            task_evidence_bundle_revision_id=task_bundle_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=work_item_id,
            match_id=match.match_id,
            official_offer_revision_id=offer_id,
            market_definition_id="md-had",
            prior=prior,
            belief=prior,
            factors=(),
            expression_bundles=(
                FaceBundleInput(bundle_code="home_draw", face_codes=("3", "1")),
            ),
            rule_ids=("k",),
            evidence_ref_tokens=(observation_id,),
            falsifier="The frozen replay evidence no longer supports the judgment.",
            rationale="Replay-only adjudication derived from frozen historical inputs.",
            commitment_tier="historical_replay_only",
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:operator-judgment",
            requested_at=decision_time + timedelta(seconds=4),
            anchor_integrity="pass",
            face_precedents=(
                FacePrecedentInput(
                    face_code="0",
                    precedent_ref="historical replay excluded-face audit anchor",
                    status="dead",
                ),
            ),
            expected_current_revision_no=0,
            expected_current_forecast_revision_no=1,
        )
    )
    judgment_id = next(
        ref.object_id
        for ref in judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=task_bundle_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=work_item_id,
            judgment_revision_ids=(judgment_id,),
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:prescription",
            requested_at=decision_time + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    prescription_id = prescription.result_refs[0].object_id
    generation = decision_actions.request_candidate_generation(
        RequestCandidateGenerationRequest(
            task_evidence_bundle_revision_id=task_bundle_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            judgment_prescription_revision_id=prescription_id,
            work_item_id=work_item_id,
            fixed_prize_policy_revision_id=None,
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:request-candidates",
            requested_at=decision_time + timedelta(seconds=6),
            expected_current_revision_no=0,
        )
    )
    generation_id = generation.result_refs[0].object_id
    generated = CandidateGenerationWorker(
        action_service=action_service,
        result_actions=OperatorResultActions(action_service),
        worker_id=f"replay-candidates-{replay_run_id}",
        lease_duration=timedelta(minutes=5),
        banded_jczq=True,
    ).run_once(limit=1, as_of=decision_time + timedelta(seconds=7))
    if len(generated) != 1:
        raise ValueError("historical replay candidate generation did not complete")

    context = decision_actions.no_ticket_decision_context(
        task_family_id=task_family_id,
        lane="jczq",
        business_key=day,
        work_item_id=work_item_id,
        as_of=decision_time + timedelta(seconds=8),
    )
    no_ticket = decision_actions.record_no_ticket(
        RecordNoTicketRequest(
            task_family_id=task_family_id,
            lane="jczq",
            business_key=day,
            work_item_id=work_item_id,
            expected_task_snapshot_hash=context.task_snapshot_hash,
            expected_scope_fingerprint=context.scope_fingerprint,
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="Replay-only formal no-ticket; no historical placement is inferred.",
            rule_ids=(),
            comparison_candidate_revision_id=None,
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=f"replay:{replay_run_id}:formal-no-ticket",
            requested_at=decision_time + timedelta(seconds=8),
        )
    )
    no_ticket_id = next(
        ref.object_id
        for ref in no_ticket.result_refs
        if ref.object_type == "no_ticket_revision"
    )
    return ReplayWorkflowResult(
        task_evidence_bundle_revision_id=task_bundle_id,
        market_prior_baseline_revision_id=baseline_id,
        baseline_envelope_revision_id=envelope_id,
        judgment_prescription_revision_id=prescription_id,
        candidate_generation_request_id=generation_id,
        no_ticket_revision_id=no_ticket_id,
    )


def _result_document(
    day_root: Path,
    manifest: ReplayInputManifest,
) -> tuple[Path, dict[str, object]] | None:
    entries = tuple(entry for entry in manifest.entries if entry.kind == "result")
    if not entries:
        return None
    if len(entries) != 1:
        raise ValueError("historical replay requires exactly one authoritative result input")
    path = day_root / entries[0].relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("authoritative result input must be an object")
    return path, document


def _prediction_face(belief: dict[str, float]) -> str:
    face_by_key = {
        "3": "3",
        "1": "1",
        "0": "0",
        "home": "3",
        "draw": "1",
        "away": "0",
    }
    normalized = {
        face_by_key[key]: float(value)
        for key, value in belief.items()
        if key in face_by_key
    }
    if set(normalized) != {"3", "1", "0"}:
        raise ValueError("replay Forecast belief is not a HAD distribution")
    return max(("3", "1", "0"), key=lambda face: normalized[face])


def _score_face(score_90: str) -> str:
    normalized = score_90.replace(":", "-")
    home_text, separator, away_text = normalized.partition("-")
    if separator != "-" or not home_text or not away_text or "-" in away_text:
        raise ValueError("authoritative result score_90 is invalid")
    home = int(home_text)
    away = int(away_text)
    return "3" if home > away else "1" if home == away else "0"


def _normalized_score(score_90: str) -> str:
    _score_face(score_90)
    return score_90.replace(":", "-")


def run_replay_results(
    action_service: ActionService,
    *,
    kernel,
    replay_run_id: str,
    day_root: Path,
    manifest: ReplayInputManifest,
    board: JczqBoard,
) -> ReplayResultSummary:
    result_input = _result_document(day_root, manifest)
    if result_input is None:
        return ReplayResultSummary(
            authoritative_result_count=0,
            replay_prediction_count=0,
            replay_score_count=0,
            rsi_statuses={
                exp_id: "replay_gap" for exp_id in ("R0", "F5", "F9")
            },
            gaps=("authoritative_results_missing",),
        )
    result_path, document = result_input
    result_time_text = next(
        entry.semantic_timestamp
        for entry in manifest.entries
        if entry.relative_path == result_path.name
    )
    if result_time_text is None:
        raise ValueError("authoritative result publication time is missing")
    result_time = datetime.fromisoformat(result_time_text.replace(" ", "T"))
    if result_time.tzinfo is None or result_time.utcoffset() is None:
        raise ValueError("authoritative result publication time must be timezone-aware")
    published_text = document.get("published_at")
    published_at = None
    if isinstance(published_text, str):
        parsed_published_at = datetime.fromisoformat(published_text.replace(" ", "T"))
        if (
            parsed_published_at.tzinfo is None
            or parsed_published_at.utcoffset() is None
        ):
            raise ValueError("authoritative result publication time must be timezone-aware")
        published_at = parsed_published_at.isoformat()
    rows = document.get("results")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("authoritative result input requires result rows")
    by_match_id = {match.match_id: match for match in board.matches}
    by_official_no = {match.official_match_no: match for match in board.matches}
    resolved: dict[str, dict[str, object]] = {}
    for row in rows:
        match = by_match_id.get(str(row.get("match_id"))) or by_official_no.get(
            str(row.get("official_match_no"))
        )
        if match is None or match.match_id in resolved:
            raise ValueError("authoritative result row has invalid or duplicate identity")
        score = row.get("score_90")
        if not isinstance(score, str):
            raise ValueError("authoritative result row is missing score_90")
        _score_face(score)
        if row.get("status") != "final":
            raise ValueError("authoritative result row is not final")
        resolved[match.match_id] = row
    if set(resolved) != set(by_match_id):
        raise ValueError("authoritative results do not cover the replay board")
    if result_time <= max(match.kickoff_at for match in board.matches):
        raise ValueError("authoritative result publication precedes replay kickoff")

    result_entry = next(
        entry for entry in manifest.entries if entry.relative_path == result_path.name
    )
    source_run_id = _stable_id("replay-result-source", replay_run_id)
    artifact_id = _stable_id("replay-result-artifact", replay_run_id)
    retrieval_id = _stable_id("replay-result-retrieval", replay_run_id)
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.connection.execute(
            insert(schema.source_runs).prefix_with("OR IGNORE").values(
                source_run_id=source_run_id,
                source_name="sporttery_result_historical_replay",
                source_type="official_result",
                started_at=result_time.isoformat(),
                finished_at=result_time.isoformat(),
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        uow.connection.execute(
            insert(schema.source_artifacts).prefix_with("OR IGNORE").values(
                artifact_id=artifact_id,
                first_recorded_at=result_time.isoformat(),
                content_type="application/json",
                storage_path=str(result_path),
                byte_size=result_entry.byte_size,
                content_hash=result_entry.sha256,
            )
        )
        uow.artifacts.insert_retrieval(
            ArtifactRetrievalRow(
                artifact_retrieval_id=retrieval_id,
                artifact_id=artifact_id,
                source_run_id=source_run_id,
                source_name="sporttery_result_historical_replay",
                source_type="official_result",
                reported_content_type="application/json",
                canonical_url=None,
                requested_url=None,
                published_at=published_at,
                retrieved_at=result_time.isoformat(),
                status="stored",
            )
        )
        forecasts = tuple(
            forecast
            for forecast in uow.decision.iter_committed_revisions()
            if forecast.match_id in by_match_id
        )
    if len(forecasts) != len(board.matches):
        raise ValueError("current replay Forecasts do not cover the board")

    actor_id = f"replay:{replay_run_id}:adjudicator"
    actor_role = ActorRole.REPLAY_ADJUDICATOR
    workflow = WorkflowActions(action_service)
    predictions: list[tuple[str, str, str]] = []
    for forecast in forecasts:
        face = _prediction_face(forecast.belief_distribution)
        registered = workflow.register_prediction(
            RegisterPredictionRequest(
                match_id=forecast.match_id,
                subject_type="match",
                subject_id=forecast.match_id,
                claim=(
                    f"forecast_revision={forecast.forecast_revision_id};had_face={face}"
                ),
                falsifier="The authoritative 90-minute HAD face differs.",
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=(
                    f"replay:{replay_run_id}:prediction:{forecast.forecast_revision_id}"
                ),
                requested_at=datetime.fromisoformat(forecast.made_at),
            )
        )
        predictions.append(
            (registered.result_refs[0].object_id, forecast.match_id, face)
        )

    outcomes = OutcomeActions(action_service)
    for match_id, row in sorted(resolved.items()):
        outcomes.record_outcome(
            RecordOutcomeRequest(
                match_id=match_id,
                score_90=_normalized_score(str(row["score_90"])),
                status="final",
                source_artifact_retrieval_ids=[retrieval_id],
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=f"replay:{replay_run_id}:outcome:{match_id}",
                requested_at=result_time,
            )
        )
    for prediction_id, match_id, predicted_face in predictions:
        actual_face = _score_face(str(resolved[match_id]["score_90"]))
        workflow.grade_prediction(
            GradePredictionRequest(
                prediction_id=prediction_id,
                outcome="hit" if predicted_face == actual_face else "miss",
                reason="graded from the frozen authoritative 90-minute result",
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=f"replay:{replay_run_id}:grade:{prediction_id}",
                requested_at=result_time + timedelta(seconds=1),
            )
        )

    from nutmeg.decision.rsi_wiring import after_settle

    rsi_statuses = after_settle(
        day=board.business_date,
        data_dir=Path(manifest.root).parents[2],
        experiments=("R0", "F5", "F9"),
        historical_replay=True,
    )
    return ReplayResultSummary(
        authoritative_result_count=len(resolved),
        replay_prediction_count=len(predictions),
        replay_score_count=len(predictions),
        rsi_statuses=rsi_statuses,
        gaps=(),
    )


__all__ = [
    "ReplayResultSummary",
    "ReplayWorkflowResult",
    "run_replay_results",
    "run_replay_workflow",
]
