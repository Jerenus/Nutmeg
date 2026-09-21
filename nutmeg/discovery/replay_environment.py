"""Prefix-only replay against recorded, verified tree edges."""

from __future__ import annotations

from nutmeg.discovery.contracts import PilotContract
from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.environment import (
    ContinueBatch,
    Observation,
    RevealedNode,
    StepResult,
    Stop,
    TerminalObservation,
    legal_actions,
    validate_action,
)
from nutmeg.discovery.sealed_tree import SealedTree


class ReplayEnvironment:
    def __init__(self, tree: SealedTree, pilot: PilotContract) -> None:
        if tree.world.pilot_contract_hash != contract_hash(pilot):
            raise ValueError("replay pilot does not match sealed world")
        self._tree = tree
        self._pilot = pilot
        self._visible: list[str] = []
        self._consumed: set[tuple[str, tuple[str, ...]]] = set()
        self._rounds = 0
        self._attempts = 0
        self._terminal = False
        self._wall_ms: int | None = 0
        self._candidate_count: int | None = 0

    def reset(self) -> Observation:
        self._visible = [self._tree.root_id]
        self._consumed.clear()
        self._rounds = 0
        self._attempts = 0
        self._terminal = False
        self._wall_ms = 0
        self._candidate_count = 0
        return self.observation()

    def observation(self) -> Observation:
        if not self._visible:
            raise ValueError("replay must reset before observation")
        nodes = {node.node_id: node for node in self._tree.nodes if node.node_id in self._visible}
        templates = tuple(self._tree.world.input_manifest.get("template_ids", ()))
        budgets = self._tree.world.resource_budget
        return Observation(
            world_id=self._tree.world.world_id,
            visible_node_ids=tuple(self._visible),
            frontier_node_ids=tuple(
                node_id for node_id in self._visible if nodes[node_id].frontier_eligible
            ),
            selectable_node_ids=tuple(
                node_id
                for node_id in self._visible
                if node_id in self._tree.evaluations and self._tree.evaluations[node_id].selectable
            ),
            legal_template_ids=templates,
            remaining_rounds=max(
                0, min(budgets.get("max_rounds", 0), self._pilot.budgets.max_rounds) - self._rounds
            ),
            remaining_nodes=max(
                0,
                min(budgets.get("max_nodes", 0), self._pilot.budgets.max_nodes)
                - 2
                - self._attempts,
            ),
            max_concurrency=min(
                budgets.get("max_concurrency", 0), self._pilot.budgets.max_concurrency
            ),
            task_family=self._tree.world.task_family,
            lane=self._tree.world.lane,
            business_date=self._tree.world.business_date,
            remaining_wall_ms=(
                max(
                    0,
                    min(
                        budgets.get("max_wall_seconds", self._pilot.budgets.max_wall_seconds),
                        self._pilot.budgets.max_wall_seconds,
                    )
                    * 1000
                    - self._wall_ms,
                )
                if self._wall_ms is not None
                else None
            ),
            remaining_candidate_generation_count=(
                max(
                    0,
                    min(
                        budgets.get(
                            "max_candidate_generation_count",
                            self._pilot.budgets.max_candidate_generation_count,
                        ),
                        self._pilot.budgets.max_candidate_generation_count,
                    )
                    - self._candidate_count,
                )
                if self._candidate_count is not None
                else None
            ),
            revealed_nodes=tuple(
                RevealedNode(
                    node_id=node_id,
                    execution_status=nodes[node_id].execution_status,
                    quality_by_band=tuple(
                        sorted(
                            (str(band), str(value))
                            for band, value in (
                                self._tree.evaluations[node_id].result.get(
                                    "best_objective_probability_by_band", {}
                                )
                                if node_id in self._tree.evaluations
                                else {}
                            ).items()
                            if value is not None
                        )
                    ),
                    artifact_manifest_hash=nodes[node_id].artifact_manifest_hash,
                    diagnostic_codes=tuple(nodes[node_id].diagnostic_codes),
                    resource_cost=tuple(
                        sorted(
                            (key, str(value) if value is not None else None)
                            for key, value in (nodes[node_id].resource_cost or {}).items()
                        )
                    ),
                )
                for node_id in self._visible
                if node_id != self._tree.root_id
            ),
        )

    def legal_actions(self) -> tuple:
        return legal_actions(self.observation())

    def continue_batch(self, action: ContinueBatch) -> StepResult:
        if self._terminal:
            raise ValueError("replay is terminal")
        items = validate_action(self.observation(), action, self._pilot)
        for item in items:
            if (item.node_id, item.template_ids) in self._consumed:
                raise ValueError("continuation was already consumed")
        recorded = tuple(
            self._tree.children_for(
                item.node_id,
                {"operator": item.operator, "template_ids": list(item.template_ids)},
            )
            for item in items
        )
        charged_attempts = sum(len(chain) or 1 for chain in recorded)
        if charged_attempts > self.observation().remaining_nodes:
            raise ValueError("node budget exhausted by recorded retry chain")
        revealed: list[str] = []
        failures: list[str] = []
        costs: dict[str, object] = {
            "attempts": charged_attempts,
            "wall_ms": 0,
            "candidate_generation_count": 0,
        }
        for item, chain in zip(items, recorded, strict=True):
            self._consumed.add((item.node_id, item.template_ids))
            if not chain:
                failures.append("branch_unavailable")
                costs["wall_ms"] = None
                costs["candidate_generation_count"] = None
                continue
            for node in chain:
                if node.node_id in self._visible:
                    raise ValueError("recorded child was already revealed")
                revealed.append(node.node_id)
                wall_ms = node.resource_cost.get("wall_ms") if node.resource_cost else None
                if isinstance(wall_ms, int) and costs["wall_ms"] is not None:
                    costs["wall_ms"] += wall_ms
                else:
                    costs["wall_ms"] = None
                count = (node.resource_cost or {}).get("candidate_generation_count")
                if isinstance(count, int) and costs["candidate_generation_count"] is not None:
                    costs["candidate_generation_count"] += count
                else:
                    costs["candidate_generation_count"] = None
                if node.execution_status == "failed":
                    failures.extend(node.diagnostic_codes)
        self._visible.extend(revealed)
        self._rounds += 1
        self._attempts += charged_attempts
        if self._wall_ms is not None and costs["wall_ms"] is not None:
            self._wall_ms += costs["wall_ms"]
        else:
            self._wall_ms = None
        if self._candidate_count is not None and costs["candidate_generation_count"] is not None:
            self._candidate_count += costs["candidate_generation_count"]
        else:
            self._candidate_count = None
        return StepResult(self.observation(), tuple(revealed), tuple(failures), costs)

    def stop(self, action: Stop) -> TerminalObservation:
        if self._terminal:
            raise ValueError("replay is terminal")
        validate_action(self.observation(), action, self._pilot)
        self._terminal = True
        return TerminalObservation(action.reason, action.selected_node_ids)
