"""Append-only discovery records and deterministic read projections."""

from __future__ import annotations

import json
from dataclasses import asdict, make_dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.discovery.models import WorldEventKind, project_world_state
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository import schema_discovery_generation as sg
from nutmeg.ontology.repository import schema_discovery_promotion as sp


def _record_type(name: str, table_name: str):
    """Derive immutable row signatures from the versioned SQL schema."""
    table = getattr(sd, table_name)
    return make_dataclass(
        name,
        [
            (
                column.name.removesuffix("_json") if column.name.endswith("_json") else column.name,
                object,
            )
            for column in table.columns
        ],
        frozen=True,
        slots=True,
    )


WorldRow = _record_type("WorldRow", "discovery_worlds")
WorldEventRow = _record_type("WorldEventRow", "discovery_world_events")
DiscoveryRunRow = _record_type("DiscoveryRunRow", "discovery_runs")
NodeRow = _record_type("NodeRow", "discovery_nodes")
NodeEvaluationRow = _record_type("NodeEvaluationRow", "discovery_node_evaluations")
PolicyRevisionRow = _record_type("PolicyRevisionRow", "exploration_policy_revisions")
PolicyParentLinkRow = _record_type("PolicyParentLinkRow", "exploration_policy_parent_links")
PolicyReplayRunRow = _record_type("PolicyReplayRunRow", "policy_replay_runs")
PolicyReplayRoundRow = _record_type("PolicyReplayRoundRow", "policy_replay_rounds")
PolicyReplayCompletionRow = _record_type("PolicyReplayCompletionRow", "policy_replay_completions")
TournamentRow = _record_type("TournamentRow", "policy_tournaments")
TournamentCandidateRow = _record_type("TournamentCandidateRow", "policy_tournament_candidates")
TournamentWorldRow = _record_type("TournamentWorldRow", "policy_tournament_worlds")
TournamentResultRow = _record_type("TournamentResultRow", "policy_tournament_results")
TournamentCompletionRow = _record_type("TournamentCompletionRow", "policy_tournament_completions")
ArchiveDecisionRow = _record_type("ArchiveDecisionRow", "policy_archive_decisions")
HoldoutExposureRow = _record_type("HoldoutExposureRow", "policy_holdout_exposures")
PolicyDeploymentRow = _record_type("PolicyDeploymentRow", "policy_deployments")
PolicyBrakeEventRow = _record_type("PolicyBrakeEventRow", "policy_brake_events")
PolicyShadowWindowRow = make_dataclass(
    "PolicyShadowWindowRow",
    [(column.name.removesuffix("_json"), object) for column in sp.policy_shadow_windows.columns],
    frozen=True,
    slots=True,
)
PolicyGenerationRoundRow = make_dataclass(
    "PolicyGenerationRoundRow",
    [(column.name.removesuffix("_json"), object) for column in sg.policy_generation_rounds.columns],
    frozen=True,
    slots=True,
)

_ROW_TYPES = {
    row_type.__name__: row_type
    for row_type in (
        WorldRow,
        WorldEventRow,
        DiscoveryRunRow,
        NodeRow,
        NodeEvaluationRow,
        PolicyRevisionRow,
        PolicyParentLinkRow,
        PolicyReplayRunRow,
        PolicyReplayRoundRow,
        PolicyReplayCompletionRow,
        TournamentRow,
        TournamentCandidateRow,
        TournamentWorldRow,
        TournamentResultRow,
        TournamentCompletionRow,
        ArchiveDecisionRow,
        HoldoutExposureRow,
        PolicyDeploymentRow,
        PolicyBrakeEventRow,
        PolicyGenerationRoundRow,
        PolicyShadowWindowRow,
    )
}

_BOOLEAN_COLUMNS = {"frontier_eligible", "selectable", "disqualified"}


class DiscoveryRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _insert(self, table_name: str, record: object) -> None:
        values = asdict(record)
        table = getattr(self._schema(table_name), table_name)
        encoded = {}
        for column in table.columns:
            field = (
                column.name.removesuffix("_json") if column.name.endswith("_json") else column.name
            )
            value = values[field]
            if column.name.endswith("_json") and value is not None:
                value = canonical_json(value)
            elif column.name in _BOOLEAN_COLUMNS:
                value = int(value)
            encoded[column.name] = value
        self._connection.execute(insert(table).values(**encoded))

    @staticmethod
    def _schema(table_name: str):
        if table_name == "policy_generation_rounds":
            return sg
        if table_name == "policy_shadow_windows":
            return sp
        return sd

    @staticmethod
    def _decode(class_name: str, row):
        if row is None:
            return None
        values = {}
        for column_name, value in row.items():
            name = (
                column_name.removesuffix("_json") if column_name.endswith("_json") else column_name
            )
            if column_name.endswith("_json") and value is not None:
                value = json.loads(value)
            elif column_name in _BOOLEAN_COLUMNS:
                value = bool(value)
            values[name] = value
        return _ROW_TYPES[class_name](**values)

    def _get(self, class_name: str, table_name: str, key: str, value: str):
        table = getattr(self._schema(table_name), table_name)
        row = (
            self._connection.execute(select(table).where(table.c[key] == value)).mappings().first()
        )
        return self._decode(class_name, row)

    def _list(self, class_name: str, table_name: str, key: str, value: str, *order: str):
        table = getattr(self._schema(table_name), table_name)
        query = (
            select(table).where(table.c[key] == value).order_by(*(table.c[item] for item in order))
        )
        return tuple(
            self._decode(class_name, r) for r in self._connection.execute(query).mappings()
        )

    def insert_world(self, row: WorldRow) -> None:
        self._insert("discovery_worlds", row)

    def insert_world_event(self, row: WorldEventRow) -> None:
        self._insert("discovery_world_events", row)

    def insert_run(self, row: DiscoveryRunRow) -> None:
        self._insert("discovery_runs", row)

    def insert_node(self, row: NodeRow) -> None:
        self._insert("discovery_nodes", row)

    def insert_node_evaluation(self, row: NodeEvaluationRow) -> None:
        self._insert("discovery_node_evaluations", row)

    def insert_policy(self, row: PolicyRevisionRow) -> None:
        self._insert("exploration_policy_revisions", row)

    def insert_generation_round(self, row: PolicyGenerationRoundRow) -> None:
        self._insert("policy_generation_rounds", row)

    def generation_round(self, round_id: str) -> PolicyGenerationRoundRow | None:
        return self._get(
            "PolicyGenerationRoundRow", "policy_generation_rounds", "generation_round_id", round_id
        )

    def insert_policy_parent_link(self, row: PolicyParentLinkRow) -> None:
        self._insert("exploration_policy_parent_links", row)

    def insert_policy_replay(self, row: PolicyReplayRunRow) -> None:
        self._insert("policy_replay_runs", row)

    def insert_policy_replay_round(self, row: PolicyReplayRoundRow) -> None:
        self._insert("policy_replay_rounds", row)

    def insert_policy_replay_completion(self, row: PolicyReplayCompletionRow) -> None:
        self._insert("policy_replay_completions", row)

    def insert_tournament(self, row: TournamentRow) -> None:
        self._insert("policy_tournaments", row)

    def insert_tournament_candidate(self, row: TournamentCandidateRow) -> None:
        self._insert("policy_tournament_candidates", row)

    def insert_tournament_world(self, row: TournamentWorldRow) -> None:
        self._insert("policy_tournament_worlds", row)

    def insert_tournament_result(self, row: TournamentResultRow) -> None:
        self._insert("policy_tournament_results", row)

    def insert_tournament_completion(self, row: TournamentCompletionRow) -> None:
        self._insert("policy_tournament_completions", row)

    def insert_archive_decision(self, row: ArchiveDecisionRow) -> None:
        self._insert("policy_archive_decisions", row)

    def insert_holdout_exposure(self, row: HoldoutExposureRow) -> None:
        self._insert("policy_holdout_exposures", row)

    def insert_deployment(self, row: PolicyDeploymentRow) -> None:
        self._insert("policy_deployments", row)

    def insert_shadow_window(self, row: PolicyShadowWindowRow) -> None:
        self._insert("policy_shadow_windows", row)

    def shadow_window(self, window_id: str) -> PolicyShadowWindowRow | None:
        return self._get(
            "PolicyShadowWindowRow", "policy_shadow_windows", "policy_shadow_window_id", window_id
        )

    def insert_brake(self, row: PolicyBrakeEventRow) -> None:
        self._insert("policy_brake_events", row)

    def world(self, world_id: str) -> WorldRow | None:
        return self._get("WorldRow", "discovery_worlds", "world_id", world_id)

    def world_events(self, world_id: str) -> tuple[WorldEventRow, ...]:
        return self._list(
            "WorldEventRow",
            "discovery_world_events",
            "world_id",
            world_id,
            "sequence_no",
            "world_event_id",
        )

    def world_state(self, world_id: str) -> str:
        return project_world_state(
            tuple(WorldEventKind(e.event_kind) for e in self.world_events(world_id))
        )

    def run(self, discovery_run_id: str) -> DiscoveryRunRow | None:
        return self._get("DiscoveryRunRow", "discovery_runs", "discovery_run_id", discovery_run_id)

    def node(self, node_id: str) -> NodeRow | None:
        return self._get("NodeRow", "discovery_nodes", "node_id", node_id)

    def nodes_for_world(self, world_id: str) -> tuple[NodeRow, ...]:
        return self._list(
            "NodeRow", "discovery_nodes", "world_id", world_id, "creation_sequence", "node_id"
        )

    def latest_node_evaluation(self, node_id: str) -> NodeEvaluationRow | None:
        table = sd.discovery_node_evaluations
        query = (
            select(table)
            .where(table.c.node_id == node_id)
            .order_by(table.c.revision_no.desc(), table.c.node_evaluation_id.desc())
            .limit(1)
        )
        return self._decode("NodeEvaluationRow", self._connection.execute(query).mappings().first())

    def policy(self, policy_revision_id: str) -> PolicyRevisionRow | None:
        return self._get(
            "PolicyRevisionRow",
            "exploration_policy_revisions",
            "policy_revision_id",
            policy_revision_id,
        )

    def policy_parents(self, policy_revision_id: str) -> tuple[str, ...]:
        links = self._list(
            "PolicyParentLinkRow",
            "exploration_policy_parent_links",
            "policy_revision_id",
            policy_revision_id,
            "parent_index",
        )
        return tuple(link.parent_policy_revision_id for link in links)

    def policy_replay(self, replay_run_id: str) -> PolicyReplayRunRow | None:
        return self._get(
            "PolicyReplayRunRow", "policy_replay_runs", "policy_replay_run_id", replay_run_id
        )

    def policy_replay_rounds(self, replay_run_id: str) -> tuple[PolicyReplayRoundRow, ...]:
        return self._list(
            "PolicyReplayRoundRow",
            "policy_replay_rounds",
            "policy_replay_run_id",
            replay_run_id,
            "round_no",
        )

    def policy_replay_completion(self, replay_run_id: str) -> PolicyReplayCompletionRow | None:
        return self._get(
            "PolicyReplayCompletionRow",
            "policy_replay_completions",
            "policy_replay_run_id",
            replay_run_id,
        )

    def tournament(self, tournament_id: str) -> TournamentRow | None:
        return self._get(
            "TournamentRow", "policy_tournaments", "policy_tournament_id", tournament_id
        )

    def tournament_candidates(self, tournament_id: str) -> tuple[TournamentCandidateRow, ...]:
        return self._list(
            "TournamentCandidateRow",
            "policy_tournament_candidates",
            "policy_tournament_id",
            tournament_id,
            "candidate_index",
        )

    def tournament_worlds(self, tournament_id: str) -> tuple[TournamentWorldRow, ...]:
        return self._list(
            "TournamentWorldRow",
            "policy_tournament_worlds",
            "policy_tournament_id",
            tournament_id,
            "world_index",
        )

    def tournament_results(self, tournament_id: str) -> tuple[TournamentResultRow, ...]:
        return self._list(
            "TournamentResultRow",
            "policy_tournament_results",
            "policy_tournament_id",
            tournament_id,
            "policy_revision_id",
            "world_id",
        )

    def tournament_completion(self, tournament_id: str) -> TournamentCompletionRow | None:
        return self._get(
            "TournamentCompletionRow",
            "policy_tournament_completions",
            "policy_tournament_id",
            tournament_id,
        )

    def latest_archive_decision(self, policy_revision_id: str) -> ArchiveDecisionRow | None:
        table = sd.policy_archive_decisions
        query = (
            select(table)
            .where(table.c.policy_revision_id == policy_revision_id)
            .order_by(table.c.decided_at.desc(), table.c.archive_decision_id.desc())
            .limit(1)
        )
        return self._decode(
            "ArchiveDecisionRow", self._connection.execute(query).mappings().first()
        )

    def archive_decisions_for_tournament(
        self, policy_tournament_id: str
    ) -> tuple[ArchiveDecisionRow, ...]:
        return self._list(
            "ArchiveDecisionRow",
            "policy_archive_decisions",
            "policy_tournament_id",
            policy_tournament_id,
            "decided_at",
            "archive_decision_id",
        )

    def exposed_holdouts(self, policy_family: str) -> tuple[HoldoutExposureRow, ...]:
        return self._list(
            "HoldoutExposureRow",
            "policy_holdout_exposures",
            "policy_family",
            policy_family,
            "exposed_at",
            "holdout_exposure_id",
        )

    def latest_deployment(self, policy_family: str) -> PolicyDeploymentRow | None:
        table = sd.policy_deployments
        query = (
            select(table)
            .where(table.c.policy_family == policy_family)
            .order_by(table.c.decided_at.desc(), table.c.policy_deployment_id.desc())
            .limit(1)
        )
        return self._decode(
            "PolicyDeploymentRow", self._connection.execute(query).mappings().first()
        )

    def deployment(self, policy_deployment_id: str) -> PolicyDeploymentRow | None:
        return self._get(
            "PolicyDeploymentRow",
            "policy_deployments",
            "policy_deployment_id",
            policy_deployment_id,
        )

    def latest_deployment_for_scope(
        self, policy_family: str, scope: dict[str, object]
    ) -> PolicyDeploymentRow | None:
        table = sd.policy_deployments
        query = (
            select(table)
            .where(
                table.c.policy_family == policy_family,
                table.c.scope_json == canonical_json(scope),
            )
            .order_by(table.c.decided_at.desc(), table.c.policy_deployment_id.desc())
            .limit(1)
        )
        return self._decode(
            "PolicyDeploymentRow", self._connection.execute(query).mappings().first()
        )

    def latest_brake(self, policy_deployment_id: str) -> PolicyBrakeEventRow | None:
        table = sd.policy_brake_events
        query = (
            select(table)
            .where(table.c.policy_deployment_id == policy_deployment_id)
            .order_by(table.c.tripped_at.desc(), table.c.policy_brake_event_id.desc())
            .limit(1)
        )
        return self._decode(
            "PolicyBrakeEventRow", self._connection.execute(query).mappings().first()
        )

    def count_sealed_worlds(self, task_family: str) -> int:
        worlds = sd.discovery_worlds
        events = sd.discovery_world_events
        latest_event = (
            select(events.c.event_kind)
            .where(events.c.world_id == worlds.c.world_id)
            .order_by(events.c.sequence_no.desc())
            .limit(1)
            .correlate(worlds)
            .scalar_subquery()
        )
        query = (
            select(func.count())
            .select_from(worlds)
            .where(
                worlds.c.task_family == task_family,
                latest_event == "sealed",
            )
        )
        return self._connection.execute(query).scalar_one()

    def counts(self) -> dict[str, int]:
        names = {
            "discovery_world_count": sd.discovery_worlds,
            "discovery_node_count": sd.discovery_nodes,
            "exploration_policy_revision_count": sd.exploration_policy_revisions,
            "policy_replay_run_count": sd.policy_replay_runs,
            "policy_tournament_count": sd.policy_tournaments,
            "policy_deployment_count": sd.policy_deployments,
        }
        return {
            name: self._connection.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in names.items()
        }
