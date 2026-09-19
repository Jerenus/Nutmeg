"""Authoritative JCZQ board intake and proposal orchestration."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.rsi_actions import FulfillDutyRequest
from nutmeg.ontology.actions.workflow_actions import CreateAgentProposalRequest
from nutmeg.ontology.operator.models import JczqBoardResearchStateRow
from nutmeg.product.operator_contracts import (
    JczqBoardProgressV1,
    JczqDecisionTerminalV1,
)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class JczqBoardMatch:
    match_id: str
    official_match_no: str
    kickoff_at: datetime

    def __post_init__(self) -> None:
        if not self.match_id.strip() or not self.official_match_no.strip():
            raise ValueError("board match identity is required")
        _aware(self.kickoff_at, "kickoff_at")


@dataclass(frozen=True, slots=True)
class JczqBoard:
    business_date: str
    matches: tuple[JczqBoardMatch, ...]

    def __post_init__(self) -> None:
        if not self.business_date.strip() or not self.matches:
            raise ValueError("board date and matches are required")
        if len({item.match_id for item in self.matches}) != len(self.matches):
            raise ValueError("board match ids must be unique")
        if len({item.official_match_no for item in self.matches}) != len(self.matches):
            raise ValueError("board match numbers must be unique")


@dataclass(frozen=True, slots=True)
class JczqResearchArtifact:
    match_id: str
    captured_at: datetime
    source_run_id: str
    artifact_id: str
    intake_errors: tuple[str, ...] = ()
    artifact_path: str | None = None
    artifact_bytes: bytes | None = None

    def __post_init__(self) -> None:
        _aware(self.captured_at, "captured_at")
        for value in (self.match_id, self.source_run_id, self.artifact_id):
            if not value.strip():
                raise ValueError("research artifact lineage is required")


@dataclass(frozen=True, slots=True)
class JczqForecastDraft:
    match_id: str
    information_cutoff_at: datetime
    kickoff_at: datetime
    payload: dict[str, object]
    citation_refs: tuple[dict[str, str], ...]
    origin: str


class _R0Actions(Protocol):
    def fulfill_duty(self, request: FulfillDutyRequest): ...


class _ProposalWriter(Protocol):
    def create_agent_proposal(self, request: CreateAgentProposalRequest): ...


class JczqBoardWorkflow:
    def __init__(
        self,
        action_service,
        *,
        r0_actions: _R0Actions | None = None,
        proposal_writer: _ProposalWriter | None = None,
        operator_actions=None,
        clock=None,
    ) -> None:
        self._action_service = action_service
        self._r0_actions = r0_actions
        self._proposal_writer = proposal_writer
        self._operator_actions = operator_actions
        self._clock = clock or (lambda: datetime.now(UTC))

    def intake_board(
        self,
        board: JczqBoard,
        artifacts: Iterable[JczqResearchArtifact],
        *,
        historical_replay: bool,
        actor_id: str = "system:jczq-board",
        actor_role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    ) -> JczqBoardProgressV1:
        by_match: dict[str, JczqResearchArtifact] = {}
        for artifact in artifacts:
            if artifact.match_id in by_match:
                raise ValueError("board match has multiple research terminal inputs")
            by_match[artifact.match_id] = artifact
        known = {item.match_id for item in board.matches}
        if set(by_match) - known:
            raise ValueError("research artifact references a match outside the board")
        now = _aware(self._clock(), "clock")
        with self._action_service.unit_of_work() as uow:
            current_by_match = {
                row.match_id: row
                for row in uow.operator_decision.jczq_board_research_states(
                    board.business_date
                )
            }
        states = []
        for match in board.matches:
            artifact = by_match.get(match.match_id)
            status = (
                current_by_match[match.match_id].status
                if artifact is None and match.match_id in current_by_match
                else "price_only"
                if artifact is None
                else "rejected"
                if artifact.intake_errors
                else "researched"
            )
            states.append((match, artifact, status))
        payload = {
            "business_date": board.business_date,
            "historical_replay": historical_replay,
            "states": [
                {
                    "match_id": match.match_id,
                    "official_match_no": match.official_match_no,
                    "status": status,
                    "source_run_id": (
                        artifact.source_run_id
                        if artifact
                        else current_by_match.get(match.match_id).source_run_id
                        if current_by_match.get(match.match_id)
                        else None
                    ),
                    "artifact_id": (
                        artifact.artifact_id
                        if artifact
                        else current_by_match.get(match.match_id).artifact_id
                        if current_by_match.get(match.match_id)
                        else None
                    ),
                    "captured_at": (
                        _aware(artifact.captured_at, "captured_at").isoformat()
                        if artifact
                        else current_by_match.get(match.match_id).captured_at
                        if current_by_match.get(match.match_id)
                        else None
                    ),
                    "kickoff_at": _aware(match.kickoff_at, "kickoff_at").isoformat(),
                }
                for match, artifact, status in states
            ],
        }
        command = ActionCommand.create(
            action_type="reconcile_jczq_board_research",
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=(
                f"jczq-board:{board.business_date}:research:"
                f"{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"
            ),
            payload=payload,
            requested_at=now,
        )

        r0_targets: list[tuple[JczqBoardMatch, JczqResearchArtifact]] = []

        def handler(uow, committed_command):
            refs = []
            for match, artifact, status in states:
                current = uow.operator_decision.current_jczq_board_research_state(
                    business_date=board.business_date,
                    match_id=match.match_id,
                )
                source_run_id = (
                    artifact.source_run_id
                    if artifact
                    else current.source_run_id
                    if current
                    else None
                )
                artifact_id = (
                    artifact.artifact_id
                    if artifact
                    else current.artifact_id
                    if current
                    else None
                )
                captured_at = (
                    _aware(artifact.captured_at, "captured_at").isoformat()
                    if artifact
                    else current.captured_at
                    if current
                    else None
                )
                if current is not None and (
                    current.status,
                    current.source_run_id,
                    current.artifact_id,
                    current.captured_at,
                    current.historical_replay,
                ) == (
                    status,
                    source_run_id,
                    artifact_id,
                    captured_at,
                    int(historical_replay),
                ):
                    refs.append(
                        ObjectRef("jczq_board_research_state", current.board_research_state_id)
                    )
                    continue
                family_id = _stable_id(
                    "jczq-board-research-family",
                    board.business_date,
                    match.match_id,
                )
                revision_no = 1 if current is None else current.revision_no + 1
                state_id = _stable_id(
                    "jczq-board-research",
                    family_id,
                    revision_no,
                    status,
                    artifact_id,
                )
                uow.operator_decision.insert_jczq_board_research_state(
                    JczqBoardResearchStateRow(
                        board_research_state_id=state_id,
                        board_research_family_id=family_id,
                        revision_no=revision_no,
                        supersedes_revision_id=(
                            None if current is None else current.board_research_state_id
                        ),
                        business_date=board.business_date,
                        match_id=match.match_id,
                        official_match_no=match.official_match_no,
                        status=status,
                        source_run_id=source_run_id,
                        artifact_id=artifact_id,
                        captured_at=captured_at,
                        kickoff_at=_aware(match.kickoff_at, "kickoff_at").isoformat(),
                        historical_replay=int(historical_replay),
                        action_id=committed_command.action_id,
                        created_at=now.isoformat(),
                    )
                )
                refs.append(ObjectRef("jczq_board_research_state", state_id))
                if status == "researched" and artifact is not None:
                    r0_targets.append((match, artifact))
            return tuple(refs)

        outcome = self._action_service.execute(command, handler)
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("JCZQ board research reconciliation did not commit")
        if (
            self._r0_actions is not None
            and not historical_replay
            and outcome.action_id == command.action_id
        ):
            for match, artifact in r0_targets:
                if _aware(artifact.captured_at, "captured_at") >= _aware(
                    match.kickoff_at, "kickoff_at"
                ):
                    continue
                if artifact.artifact_path is None or artifact.artifact_bytes is None:
                    raise ValueError("R0 fulfillment requires artifact path and bytes")
                self._r0_actions.fulfill_duty(
                    FulfillDutyRequest(
                        exp_id="R0",
                        duty_name="match-research",
                        day=board.business_date,
                        artifact_path=artifact.artifact_path,
                        artifact_bytes=artifact.artifact_bytes,
                        n_rows=1,
                        population_stratum="jczq",
                        judgment_tier_hist={"deep_research": 1},
                        captured_at=artifact.captured_at,
                        earliest_kickoff=match.kickoff_at.isoformat(),
                        match_id=match.match_id,
                        actor_id="system:jczq-board",
                        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                        idempotency_key=_stable_id(
                            "rsi-r0-fulfillment",
                            board.business_date,
                            match.match_id,
                            artifact.artifact_id,
                        ),
                        requested_at=now,
                    )
                )
        return self.progress(board.business_date)

    def progress(self, business_date: str) -> JczqBoardProgressV1:
        with self._action_service.unit_of_work() as uow:
            rows = uow.operator_decision.jczq_board_research_states(business_date)
        counts = Counter(row.status for row in rows)
        return JczqBoardProgressV1(
            business_date=business_date,
            total=len(rows),
            researched=counts.get("researched", 0),
            rejected=counts.get("rejected", 0),
            price_only=counts.get("price_only", 0),
            match_ids=[row.match_id for row in rows],
        )

    def propose_forecasts(
        self,
        drafts: Iterable[JczqForecastDraft],
        *,
        historical_replay: bool,
    ) -> tuple[object, ...]:
        if self._proposal_writer is None:
            raise ValueError("proposal writer is not configured")
        results = []
        for draft in drafts:
            cutoff = _aware(draft.information_cutoff_at, "information_cutoff_at")
            kickoff = _aware(draft.kickoff_at, "kickoff_at")
            if cutoff > kickoff and not historical_replay:
                raise ValueError("post-kickoff evidence cannot be prospective")
            payload = dict(draft.payload)
            payload.update(
                {
                    "historical_replay": historical_replay,
                    "prospective": not historical_replay and cutoff <= kickoff,
                }
            )
            results.append(
                self._proposal_writer.create_agent_proposal(
                    CreateAgentProposalRequest(
                        subject_type="match",
                        subject_id=draft.match_id,
                        proposal_type="forecast_draft",
                        information_cutoff_at=cutoff.isoformat(),
                        operator_prompt="JCZQ board forecast draft",
                        payload=payload,
                        citation_refs=list(draft.citation_refs),
                        model_name=draft.origin,
                        model_version="jczq-board-v2",
                        actor_id=draft.origin,
                        actor_role=ActorRole.AI_ANALYST,
                        idempotency_key=_stable_id(
                            "jczq-forecast-proposal",
                            draft.match_id,
                            cutoff.isoformat(),
                        ),
                        requested_at=_aware(self._clock(), "clock"),
                    )
                )
            )
        return tuple(results)

    def require_terminal_state(self, business_date: str) -> JczqDecisionTerminalV1:
        task_family_id = f"jczq:{business_date}"
        with self._action_service.unit_of_work() as uow:
            selections = (
                uow.operator_decision.current_candidate_selections_for_task_family(
                    task_family_id
                )
            )
            no_tickets = tuple(
                row
                for row in uow.operator_result.current_no_ticket_revisions_for_task_family(
                    task_family_id
                )
                if row.deployment_outcome != "reopened"
            )
        terminal_count = len(selections) + len(no_tickets)
        if terminal_count == 0:
            raise ValueError("terminal decision is missing")
        if terminal_count != 1:
            raise ValueError("terminal decision is not unique")
        if selections:
            selection = selections[0]
            with self._action_service.unit_of_work() as uow:
                candidate = uow.operator_result.candidate(selection.candidate_revision_id)
            if candidate is None:
                raise ValueError("terminal selection candidate is missing")
            audit_complete = (
                candidate.partition == "eligible"
                and candidate.deployable == 1
                and candidate.leg_audit_completed == 1
                and candidate.prescription_audit_completed == 1
                and candidate.budget_check_completed == 1
                and candidate.deployment_report_completed == 1
            )
            if not audit_complete:
                raise ValueError("terminal decision audit is incomplete")
            return JczqDecisionTerminalV1(
                business_date=business_date,
                kind="selected",
                selection_revision_id=selection.candidate_selection_id,
                no_ticket_revision_id=None,
                candidate_set_revision_id=selection.candidate_set_revision_id,
                audit_complete=audit_complete,
            )
        no_ticket = no_tickets[0]
        return JczqDecisionTerminalV1(
            business_date=business_date,
            kind="no_ticket",
            selection_revision_id=None,
            no_ticket_revision_id=no_ticket.no_ticket_revision_id,
            candidate_set_revision_id=None,
            audit_complete=True,
        )

    def commit_judgment(self, command, *, actor_id: str, actor_role: ActorRole):
        if self._operator_actions is None:
            raise ValueError("operator actions are not configured")
        return self._operator_actions.commit_match_judgment(
            command,
            actor_id=actor_id,
            actor_role=actor_role,
        )


__all__ = [
    "JczqBoard",
    "JczqBoardMatch",
    "JczqBoardWorkflow",
    "JczqForecastDraft",
    "JczqResearchArtifact",
]
