"""Bounded, shadow-only recording of the frozen structural baseline."""

from __future__ import annotations

import hashlib
import multiprocessing
import queue
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping
from urllib.parse import quote

from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_pilot_contract
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
from nutmeg.discovery.online_adapter import ShardExecution, execute_template_shard
from nutmeg.discovery.online_inputs import (
    StructuralInputSnapshot,
    read_structural_input_from_database,
    snapshot_payload,
)
from nutmeg.ontology.actions.discovery_world_actions import (
    CreateDiscoveryWorldRequest,
    DiscoveryWorldActions,
    RecordDiscoveryFailureRequest,
    RecordDiscoveryNodeRequest,
    SealDiscoveryWorldRequest,
    StartDiscoveryRunRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.discovery import (
    DiscoveryRunRow,
    NodeEvaluationRow,
    NodeRow,
    WorldRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_PILOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


@dataclass(frozen=True, slots=True)
class RecordedWorld:
    world_id: str
    sealed_manifest_hash: str
    selected_node_ids: tuple[str, ...]


def board_size_stratum(offer_count: int) -> str:
    if offer_count <= 4:
        return "small"
    if offer_count <= 9:
        return "medium"
    return "large"


def _source_fingerprint(database: Path) -> str:
    if not database.is_file():
        raise ValueError("source database does not exist")
    uri = f"file:{quote(str(database.resolve()), safe='/')}?mode=ro"
    digest = hashlib.sha256()
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        tables = sorted(
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not name.startswith("sqlite_")
        )
        for name in tables:
            digest.update(name.encode("utf-8"))
            table_identifier = '"' + name.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({table_identifier})").fetchall()
            order = ", ".join('"' + column[1].replace('"', '""') + '"' for column in columns)
            for row in connection.execute(f"SELECT * FROM {table_identifier} ORDER BY {order}"):
                digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


def _committed(outcome) -> None:
    if outcome.status is not ActionStatus.COMMITTED:
        raise ValueError(f"shadow Action did not commit: {outcome.status}")


def _commit_attempt(fn, request) -> None:
    for attempt in range(2):
        try:
            _committed(fn(request))
            return
        except (sqlite3.OperationalError, SqlAlchemyOperationalError):
            if attempt:
                raise


def _failed_shard(snapshot, template_id, diagnostics, *, wall_ms=None) -> ShardExecution:
    artifact = {
        "snapshot_hash": snapshot.manifest_hash,
        "template_ids": [template_id],
        "status": "failed",
        "diagnostic_codes": diagnostics,
    }
    digest = canonical_hash(artifact)
    return ShardExecution(
        template_ids=(template_id,),
        status="failed",
        artifact_manifest={**artifact, "content_hash": digest},
        artifact_hash=digest,
        diagnostic_codes=diagnostics,
        resource_cost={"wall_ms": wall_ms, "candidate_generation_count": None},
        evaluation=None,
        selectable=False,
    )


def _process_shard_entry(results, snapshot, template_id, pilot, worker_fn) -> None:
    try:
        results.put(worker_fn(snapshot, template_id, pilot))
    except Exception as exc:
        results.put(_failed_shard(snapshot, template_id, ("adapter_crash", type(exc).__name__)))


def run_shard_isolated(
    snapshot: StructuralInputSnapshot,
    template_id: str,
    pilot,
    *,
    timeout_seconds: float,
    worker_fn: Callable | None = None,
) -> ShardExecution:
    """Run real shadow work in a killable process with no Action or DB handle."""
    if timeout_seconds <= 0:
        return _failed_shard(snapshot, template_id, ("timeout",), wall_ms=0)
    context = multiprocessing.get_context("spawn")
    results = context.Queue(maxsize=1)
    process = context.Process(
        target=_process_shard_entry,
        args=(results, snapshot, template_id, pilot, worker_fn or _run_shard),
        daemon=True,
    )
    started = monotonic()
    try:
        process.start()
        try:
            return results.get(timeout=max(0, timeout_seconds - (monotonic() - started)))
        except queue.Empty:
            return _failed_shard(
                snapshot,
                template_id,
                ("timeout",),
                wall_ms=max(1, round((monotonic() - started) * 1000)),
            )
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join()
        results.close()


def _run_shard(snapshot, template_id, pilot) -> ShardExecution:
    try:
        result = execute_template_shard(
            snapshot,
            (template_id,),
            pilot=pilot,
            candidate_count_limit=(
                pilot.budgets.max_candidate_generation_count // len(snapshot.template_ids)
            ),
            max_wall_seconds=pilot.budgets.max_wall_seconds,
        )
        artifact = result.artifact_manifest
        content = {key: value for key, value in artifact.items() if key != "content_hash"}
        if (
            result.template_ids != (template_id,)
            or artifact.get("content_hash") != result.artifact_hash
            or canonical_hash(content) != result.artifact_hash
        ):
            return replace(
                _failed_shard(snapshot, template_id, ("invalid_artifact",)),
                resource_cost=result.resource_cost,
            )
        return result
    except Exception as exc:
        return _failed_shard(snapshot, template_id, ("adapter_crash", type(exc).__name__))


def _validate_recording(
    snapshot: StructuralInputSnapshot,
    *,
    engine: Engine,
    shadow_database: Path,
    source_database: Path,
    policy_revision_id: str,
    requested_at: datetime,
    fixture_only: bool = False,
    generation_request_id: str | None = None,
    approval: Mapping[str, object] | None = None,
) -> tuple[object, dict[str, object], str]:
    if shadow_database.resolve() == source_database.resolve():
        raise ValueError("source and shadow stores must be distinct")
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("recording requires a timezone-aware time")
    if not fixture_only and snapshot.source_identity != str(source_database.resolve()):
        raise ValueError("prospective world requires an attested source snapshot")
    if not fixture_only:
        if approval is None:
            raise ValueError("prospective world requires explicit operator approval")
        expected_scope = {
            "source_db": str(source_database.resolve()),
            "shadow_db": str(shadow_database.resolve()),
            "generation_request_id": generation_request_id,
            "cutoff_at": snapshot.cutoff_at,
            "policy_revision_id": policy_revision_id,
        }
        if approval.get("scope") != expected_scope:
            raise ValueError("approval scope does not match frozen input")
        try:
            approved_at = datetime.fromisoformat(str(approval["approved_at"]))
            cutoff = datetime.fromisoformat(snapshot.cutoff_at)
        except (KeyError, ValueError) as exc:
            raise ValueError("approval time is invalid") from exc
        now = datetime.now(UTC)
        if (
            not approval.get("approval_id")
            or not approval.get("approved_by")
            or approved_at.tzinfo is None
            or approved_at.utcoffset() is None
            or approved_at > cutoff
            or cutoff > requested_at
            or requested_at - cutoff > timedelta(hours=24)
            or cutoff > now
            or now - cutoff > timedelta(hours=24)
            or requested_at > now
        ):
            raise ValueError("prospective approval is missing or expired")
        with OntologyUnitOfWork(engine) as uow:
            policy = uow.discovery.policy(policy_revision_id)
        from nutmeg.discovery.contracts import load_baseline_policy

        baseline_path = (
            Path(__file__).resolve().parents[2]
            / "experiments/discovery/structural-baseline-v1.policy.json"
        )
        if (
            policy is None
            or policy.created_by != approval["approved_by"]
            or not policy.validation_result.get("valid")
            or policy.source_artifact_hash != contract_hash(load_baseline_policy(baseline_path))
        ):
            raise ValueError("approval operator must own the registered baseline")
    before = _source_fingerprint(source_database)
    if not fixture_only:
        if not generation_request_id:
            raise ValueError("prospective world requires a source request")
        try:
            verified = read_structural_input_from_database(
                source_database, generation_request_id, cutoff_at=snapshot.cutoff_at
            )
        except Exception as exc:
            raise ValueError("source request cannot be independently verified") from exc
        if verified.manifest_hash != snapshot.manifest_hash:
            raise ValueError("source request snapshot differs from frozen input")
        if _source_fingerprint(source_database) != before:
            raise ValueError("protected source changed during snapshot verification")
    if (
        engine.url.database is None
        or Path(engine.url.database).resolve() != shadow_database.resolve()
    ):
        raise ValueError("shadow engine must point to the declared shadow store")
    pilot = load_pilot_contract(_PILOT_PATH)
    if pilot.mode != "shadow_only" or policy_revision_id != "structural-baseline-v1":
        raise ValueError("D2 only records the frozen shadow baseline")
    manifest = snapshot_payload(snapshot)
    if canonical_hash(manifest) != snapshot.manifest_hash:
        raise ValueError("frozen input manifest mismatch")
    if len(snapshot.template_ids) + 2 > pilot.budgets.max_nodes:
        raise ValueError("world exceeds frozen node budget")
    return pilot, manifest, before


def _create_world_and_run(
    snapshot: StructuralInputSnapshot,
    *,
    engine: Engine,
    shadow_database: Path,
    policy_revision_id: str,
    requested_at: datetime,
    pilot,
    manifest: dict[str, object],
    fixture_only: bool,
) -> tuple[str, str, str, DiscoveryWorldActions]:
    world_id = (
        f"discovery-world-{canonical_hash([snapshot.manifest_hash, policy_revision_id])[:24]}"
    )
    root_id, run_id = f"{world_id}:root", f"{world_id}:run"
    created_at = requested_at.isoformat()
    world = WorldRow(
        world_id=world_id,
        task_family=pilot.task_family,
        business_date=snapshot.business_date,
        lane=pilot.lane,
        strata={"board_size": board_size_stratum(len(snapshot.candidate_input.offers))},
        input_manifest_hash=canonical_hash(manifest),
        input_manifest=manifest,
        pilot_contract_hash=contract_hash(pilot),
        legal_action_schema={"operators": [operator.name for operator in pilot.operator_grammar]},
        evaluator_revision=pilot.evaluator.revision,
        resource_budget=pilot.budgets.model_dump(),
        cutoff_at=snapshot.cutoff_at,
        provenance_mode="historical_replay_source" if fixture_only else "prospective_online",
        isolated_store_identity=f"shadow:{shadow_database.resolve()}",
        root_node_id=root_id,
        created_at=created_at,
        action_id="pending",
    )
    root = NodeRow(
        node_id=root_id,
        world_id=world_id,
        discovery_run_id=None,
        parent_node_id=None,
        depth=0,
        sibling_order=0,
        creation_sequence=1,
        continuation_action=None,
        policy_decision=None,
        artifact_manifest_hash=snapshot.manifest_hash,
        artifact_manifest=manifest,
        business_refs=[asdict(reference) for reference in snapshot.references],
        execution_status="complete",
        diagnostic_codes=[],
        started_at=created_at,
        finished_at=created_at,
        latency_ms=0,
        resource_cost={"wall_ms": 0},
        retry_of_node_id=None,
        terminal_reason=None,
        frontier_eligible=True,
        visibility_sequence=1,
        action_id="pending",
    )
    actions = DiscoveryWorldActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    _committed(
        actions.create_world(
            CreateDiscoveryWorldRequest(
                world=world,
                root=root,
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"{world_id}:create",
                requested_at=requested_at,
            )
        )
    )
    _committed(
        actions.start_run(
            StartDiscoveryRunRequest(
                run=DiscoveryRunRow(
                    discovery_run_id=run_id,
                    world_id=world_id,
                    policy_revision_id=policy_revision_id,
                    environment_mode="shadow",
                    started_at=created_at,
                    action_id="pending",
                ),
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"{world_id}:run",
                requested_at=requested_at,
            )
        )
    )
    return world_id, root_id, run_id, actions


def record_shadow_world(
    snapshot: StructuralInputSnapshot,
    *,
    engine: Engine,
    shadow_database: Path,
    source_database: Path,
    policy_revision_id: str,
    requested_at: datetime,
    fixture_only: bool = False,
    generation_request_id: str | None = None,
    approval: Mapping[str, object] | None = None,
) -> RecordedWorld:
    pilot, manifest, before = _validate_recording(
        snapshot,
        engine=engine,
        shadow_database=shadow_database,
        source_database=source_database,
        policy_revision_id=policy_revision_id,
        requested_at=requested_at,
        fixture_only=fixture_only,
        generation_request_id=generation_request_id,
        approval=approval,
    )
    world_id, root_id, run_id, actions = _create_world_and_run(
        snapshot,
        engine=engine,
        shadow_database=shadow_database,
        policy_revision_id=policy_revision_id,
        requested_at=requested_at,
        pilot=pilot,
        manifest=manifest,
        fixture_only=fixture_only,
    )
    created_at = requested_at.isoformat()

    # Work is done outside all Action transactions. Visibility is assigned in
    # frozen template order, never in worker completion order.
    deadline = monotonic() + pilot.budgets.max_wall_seconds

    def execute(template_id):
        if fixture_only:
            return _run_shard(snapshot, template_id, pilot)
        return run_shard_isolated(
            snapshot,
            template_id,
            pilot,
            timeout_seconds=max(0, deadline - monotonic()),
        )

    with ThreadPoolExecutor(
        max_workers=min(len(snapshot.template_ids), pilot.budgets.max_concurrency)
    ) as executor:
        results = tuple(executor.map(execute, snapshot.template_ids))
    attempts: list[tuple[str, ShardExecution, str | None]] = [
        (template_id, result, None)
        for template_id, result in zip(snapshot.template_ids, results, strict=True)
    ]
    best_by_band: dict[str, tuple[Decimal, str]] = {}
    position = 0
    while position < len(attempts):
        template_id, result, retry_of = attempts[position]
        sequence = position + 2
        node_id = f"{world_id}:attempt:{sequence - 1}"
        node = NodeRow(
            node_id=node_id,
            world_id=world_id,
            discovery_run_id=run_id,
            parent_node_id=root_id,
            depth=1,
            sibling_order=sequence - 1,
            creation_sequence=sequence,
            continuation_action={
                "operator": "enumerate_template_shard",
                "template_ids": [template_id],
            },
            policy_decision={"policy_revision_id": policy_revision_id, "round": 1},
            artifact_manifest_hash=canonical_hash(result.artifact_manifest),
            artifact_manifest=result.artifact_manifest,
            business_refs=[asdict(reference) for reference in snapshot.references],
            execution_status="failed" if result.status == "failed" else "complete",
            diagnostic_codes=list(result.diagnostic_codes),
            started_at=created_at,
            finished_at=created_at,
            latency_ms=result.resource_cost["wall_ms"],
            resource_cost=result.resource_cost,
            retry_of_node_id=retry_of,
            terminal_reason=result.status,
            frontier_eligible=result.selectable,
            visibility_sequence=sequence,
            action_id="pending",
        )
        common = dict(
            node=node,
            actor_id="sys:discovery",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"{world_id}:node:{sequence}",
            requested_at=requested_at,
        )
        if result.status == "failed":
            _commit_attempt(actions.record_failure, RecordDiscoveryFailureRequest(**common))
        else:
            evaluation = NodeEvaluationRow(
                node_evaluation_id=f"{node_id}:evaluation",
                node_id=node_id,
                revision_no=1,
                supersedes_evaluation_id=None,
                evaluator_revision=pilot.evaluator.revision,
                result=result.evaluation or {},
                selectable=result.selectable,
                evaluated_at=created_at,
                action_id="pending",
            )
            _commit_attempt(
                actions.record_node, RecordDiscoveryNodeRequest(evaluation=evaluation, **common)
            )
            if result.selectable:
                quality = (result.evaluation or {}).get("best_objective_probability_by_band", {})
                for band, probability in quality.items():
                    if probability is None:
                        continue
                    score = Decimal(probability)
                    previous = best_by_band.get(band)
                    if (
                        previous is None
                        or score > previous[0]
                        or (score == previous[0] and node_id < previous[1])
                    ):
                        best_by_band[band] = (score, node_id)
        if (
            result.status == "failed"
            and retry_of is None
            and set(result.diagnostic_codes) & {"adapter_crash", "adapter_error", "timeout"}
            and result.resource_cost.get("candidate_generation_count") is not None
            and len(attempts) + 2 < pilot.budgets.max_nodes
            and monotonic() < deadline
            and sum(
                recorded.resource_cost.get("candidate_generation_count") or 0
                for _shard, recorded, _parent in attempts[: position + 1]
            )
            < pilot.budgets.max_candidate_generation_count
        ):
            attempts.insert(position + 1, (template_id, execute(template_id), node_id))
        position += 1
    selected = sorted({node_id for _score, node_id in best_by_band.values()})
    known_candidates = sum(
        result.resource_cost.get("candidate_generation_count") or 0
        for _template_id, result, _parent in attempts
    )
    if known_candidates > pilot.budgets.max_candidate_generation_count:
        raise ValueError("candidate budget exceeded; shadow world remains unsealed")
    if _source_fingerprint(source_database) != before:
        raise ValueError("protected source changed during shadow recording; sealing blocked")
    costs = [result.resource_cost.get("wall_ms") for _template_id, result, _parent in attempts]
    unknown_cost = any(cost is None for cost in costs)
    wall_exhausted = sum(cost or 0 for cost in costs) > pilot.budgets.max_wall_seconds * 1000
    stop_reason = (
        "unknown_cost"
        if unknown_cost
        else "wall_budget_exhausted"
        if wall_exhausted
        else "best_audit_clean_node_per_band"
        if selected
        else "no_solution"
    )
    stop_manifest = {
        "selected_node_ids": selected,
        "reason": stop_reason,
    }
    stop_sequence = len(attempts) + 2
    stop = NodeRow(
        node_id=f"{world_id}:stop",
        world_id=world_id,
        discovery_run_id=run_id,
        parent_node_id=root_id,
        depth=1,
        sibling_order=stop_sequence - 1,
        creation_sequence=stop_sequence,
        continuation_action={"operator": "stop", "selected_node_ids": selected},
        policy_decision={"policy_revision_id": policy_revision_id, "round": 2},
        artifact_manifest_hash=canonical_hash(stop_manifest),
        artifact_manifest=stop_manifest,
        business_refs=[],
        execution_status="complete",
        diagnostic_codes=[stop_reason] if unknown_cost or wall_exhausted else [],
        started_at=created_at,
        finished_at=created_at,
        latency_ms=0,
        resource_cost={"wall_ms": 0, "candidate_generation_count": 0},
        retry_of_node_id=None,
        terminal_reason="policy_stop" if selected else "no_solution",
        frontier_eligible=False,
        visibility_sequence=stop_sequence,
        action_id="pending",
    )
    _commit_attempt(
        actions.record_node,
        RecordDiscoveryNodeRequest(
            node=stop,
            evaluation=None,
            actor_id="sys:discovery",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"{world_id}:stop",
            requested_at=requested_at,
        ),
    )
    with OntologyUnitOfWork(engine) as uow:
        persisted = uow.discovery.world(world_id)
        nodes = uow.discovery.nodes_for_world(world_id)
    seal_hash = actions.seal_manifest(persisted, nodes)
    _committed(
        actions.seal_world(
            SealDiscoveryWorldRequest(
                world_id=world_id,
                terminal_reason=(
                    "budget_exhausted"
                    if wall_exhausted and selected
                    else "unknown_cost"
                    if unknown_cost and selected
                    else "policy_stop"
                    if selected
                    else "no_solution"
                ),
                sealed_manifest_hash=seal_hash,
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"{world_id}:seal",
                requested_at=requested_at,
            )
        )
    )
    return RecordedWorld(world_id, seal_hash, tuple(selected))


class OnlineRecordingEnvironment:
    """Incremental D2 shadow execution behind the shared D3 policy interface."""

    def __init__(
        self,
        snapshot: StructuralInputSnapshot,
        *,
        engine: Engine,
        shadow_database: Path,
        source_database: Path,
        policy_revision_id: str,
        requested_at: datetime,
        fixture_only: bool = False,
        generation_request_id: str | None = None,
        approval: Mapping[str, object] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._engine = engine
        self._shadow_database = shadow_database
        self._source_database = source_database
        self._policy_revision_id = policy_revision_id
        self._requested_at = requested_at
        self._fixture_only = fixture_only
        self._generation_request_id = generation_request_id
        self._approval = approval
        self._world_id: str | None = None
        self._visible: list[str] = []
        self._used: set[tuple[str, tuple[str, ...]]] = set()
        self._rounds = 0
        self._attempts = 0
        self._candidate_count = 0
        self._deadline = 0.0
        self._terminal = False

    def reset(self) -> Observation:
        if self._world_id is not None:
            raise ValueError("online world already started")
        self._pilot, manifest, self._source_before = _validate_recording(
            self._snapshot,
            engine=self._engine,
            shadow_database=self._shadow_database,
            source_database=self._source_database,
            policy_revision_id=self._policy_revision_id,
            requested_at=self._requested_at,
            fixture_only=self._fixture_only,
            generation_request_id=self._generation_request_id,
            approval=self._approval,
        )
        self._world_id, self._root_id, self._run_id, self._actions = _create_world_and_run(
            self._snapshot,
            engine=self._engine,
            shadow_database=self._shadow_database,
            policy_revision_id=self._policy_revision_id,
            requested_at=self._requested_at,
            pilot=self._pilot,
            manifest=manifest,
            fixture_only=self._fixture_only,
        )
        self._visible = [self._root_id]
        self._deadline = monotonic() + self._pilot.budgets.max_wall_seconds
        return self.observation()

    def observation(self) -> Observation:
        if self._world_id is None:
            raise ValueError("online world has not started")
        with OntologyUnitOfWork(self._engine) as uow:
            nodes = {node.node_id: node for node in uow.discovery.nodes_for_world(self._world_id)}
            evaluations = {
                node_id: evaluation
                for node_id in self._visible
                if (evaluation := uow.discovery.latest_node_evaluation(node_id)) is not None
            }
        return Observation(
            world_id=self._world_id,
            visible_node_ids=tuple(self._visible),
            frontier_node_ids=tuple(
                node_id for node_id in self._visible if nodes[node_id].frontier_eligible
            ),
            selectable_node_ids=tuple(
                node_id
                for node_id in self._visible
                if node_id in evaluations and evaluations[node_id].selectable
            ),
            legal_template_ids=tuple(self._snapshot.template_ids),
            remaining_rounds=self._pilot.budgets.max_rounds - self._rounds,
            remaining_nodes=self._pilot.budgets.max_nodes - 2 - self._attempts,
            max_concurrency=self._pilot.budgets.max_concurrency,
            task_family=self._pilot.task_family,
            lane=self._pilot.lane,
            business_date=self._snapshot.business_date,
            remaining_wall_ms=max(0, round((self._deadline - monotonic()) * 1000)),
            remaining_candidate_generation_count=(
                max(0, self._pilot.budgets.max_candidate_generation_count - self._candidate_count)
                if self._candidate_count is not None
                else None
            ),
            revealed_nodes=tuple(
                RevealedNode(
                    node_id=node_id,
                    execution_status=nodes[node_id].execution_status,
                    quality_by_band=tuple(
                        sorted(
                            (str(band), str(score))
                            for band, score in (
                                evaluations[node_id].result.get(
                                    "best_objective_probability_by_band", {}
                                )
                                if node_id in evaluations
                                else {}
                            ).items()
                            if score is not None
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
                if node_id != self._root_id
            ),
        )

    def legal_actions(self) -> tuple:
        return legal_actions(self.observation())

    def continue_batch(self, action: ContinueBatch) -> StepResult:
        if self._terminal:
            raise ValueError("online world is terminal")
        items = validate_action(self.observation(), action, self._pilot)
        if any(len(item.template_ids) != 1 for item in items):
            raise ValueError("online shard continuation requires a single template")
        if any((item.node_id, item.template_ids) in self._used for item in items):
            raise ValueError("continuation was already consumed")
        if monotonic() >= self._deadline:
            raise ValueError("online wall budget exhausted")

        def execute(item):
            if self._fixture_only:
                return _run_shard(self._snapshot, item.template_ids[0], self._pilot)
            return run_shard_isolated(
                self._snapshot,
                item.template_ids[0],
                self._pilot,
                timeout_seconds=max(0, self._deadline - monotonic()),
            )

        with ThreadPoolExecutor(max_workers=len(items)) as executor:
            results = tuple(executor.map(execute, items))
        attempts = [(item, result, None) for item, result in zip(items, results, strict=True)]
        with OntologyUnitOfWork(self._engine) as uow:
            recorded_nodes = uow.discovery.nodes_for_world(self._world_id)
        parents = {node.node_id: node for node in recorded_nodes}
        sibling_counts = {
            parent.node_id: sum(node.parent_node_id == parent.node_id for node in recorded_nodes)
            for parent in parents.values()
        }
        revealed: list[str] = []
        failures: list[str] = []
        wall_ms: int | None = 0
        position = 0
        while position < len(attempts):
            item, result, retry_of = attempts[position]
            sequence = self._attempts + 2
            node_id = f"{self._world_id}:attempt:{self._attempts + 1}"
            now = self._requested_at.isoformat()
            sibling_counts[item.node_id] += 1
            node = NodeRow(
                node_id=node_id,
                world_id=self._world_id,
                discovery_run_id=self._run_id,
                parent_node_id=item.node_id,
                depth=parents[item.node_id].depth + 1,
                sibling_order=sibling_counts[item.node_id],
                creation_sequence=sequence,
                continuation_action={
                    "operator": item.operator,
                    "template_ids": list(item.template_ids),
                },
                policy_decision={
                    "policy_revision_id": self._policy_revision_id,
                    "round": self._rounds + 1,
                },
                artifact_manifest_hash=canonical_hash(result.artifact_manifest),
                artifact_manifest=result.artifact_manifest,
                business_refs=[asdict(reference) for reference in self._snapshot.references],
                execution_status="failed" if result.status == "failed" else "complete",
                diagnostic_codes=list(result.diagnostic_codes),
                started_at=now,
                finished_at=now,
                latency_ms=result.resource_cost.get("wall_ms"),
                resource_cost=result.resource_cost,
                retry_of_node_id=retry_of,
                terminal_reason=result.status,
                frontier_eligible=result.selectable,
                visibility_sequence=sequence,
                action_id="pending",
            )
            common = dict(
                node=node,
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"{self._world_id}:node:{sequence}",
                requested_at=self._requested_at,
            )
            if result.status == "failed":
                _commit_attempt(
                    self._actions.record_failure, RecordDiscoveryFailureRequest(**common)
                )
                failures.extend(result.diagnostic_codes)
            else:
                evaluation = NodeEvaluationRow(
                    node_evaluation_id=f"{node_id}:evaluation",
                    node_id=node_id,
                    revision_no=1,
                    supersedes_evaluation_id=None,
                    evaluator_revision=self._pilot.evaluator.revision,
                    result=result.evaluation or {},
                    selectable=result.selectable,
                    evaluated_at=now,
                    action_id="pending",
                )
                _commit_attempt(
                    self._actions.record_node,
                    RecordDiscoveryNodeRequest(evaluation=evaluation, **common),
                )
            self._used.add((item.node_id, item.template_ids))
            self._attempts += 1
            revealed.append(node_id)
            count = result.resource_cost.get("candidate_generation_count")
            if count is None:
                self._candidate_count = None
            elif self._candidate_count is not None:
                self._candidate_count += count
            cost = result.resource_cost.get("wall_ms")
            wall_ms = wall_ms + cost if wall_ms is not None and isinstance(cost, int) else None
            if (
                result.status == "failed"
                and retry_of is None
                and set(result.diagnostic_codes) & {"adapter_crash", "adapter_error", "timeout"}
                and self._candidate_count is not None
                and self._candidate_count < self._pilot.budgets.max_candidate_generation_count
                and self._attempts + len(attempts) - position - 1
                < self._pilot.budgets.max_nodes - 2
                and monotonic() < self._deadline
            ):
                attempts.insert(position + 1, (item, execute(item), node_id))
            position += 1
        self._visible.extend(revealed)
        self._rounds += 1
        if self._candidate_count is not None and (
            self._candidate_count > self._pilot.budgets.max_candidate_generation_count
        ):
            raise ValueError("candidate budget exceeded; shadow world remains unsealed")
        return StepResult(
            self.observation(),
            tuple(revealed),
            tuple(failures),
            {"attempts": len(attempts), "wall_ms": wall_ms},
        )

    def stop(self, action: Stop) -> TerminalObservation:
        if self._terminal:
            raise ValueError("online world is terminal")
        validate_action(self.observation(), action, self._pilot)
        if _source_fingerprint(self._source_database) != self._source_before:
            raise ValueError("protected source changed during shadow recording; sealing blocked")
        with OntologyUnitOfWork(self._engine) as uow:
            recorded = uow.discovery.nodes_for_world(self._world_id)
        sequence = len(recorded) + 1
        now = self._requested_at.isoformat()
        manifest = {"selected_node_ids": list(action.selected_node_ids), "reason": action.reason}
        stop = NodeRow(
            node_id=f"{self._world_id}:stop",
            world_id=self._world_id,
            discovery_run_id=self._run_id,
            parent_node_id=self._root_id,
            depth=1,
            sibling_order=sequence - 1,
            creation_sequence=sequence,
            continuation_action={
                "operator": "stop",
                "selected_node_ids": list(action.selected_node_ids),
            },
            policy_decision={
                "policy_revision_id": self._policy_revision_id,
                "round": self._rounds + 1,
            },
            artifact_manifest_hash=canonical_hash(manifest),
            artifact_manifest=manifest,
            business_refs=[],
            execution_status="complete",
            diagnostic_codes=[],
            started_at=now,
            finished_at=now,
            latency_ms=0,
            resource_cost={"wall_ms": 0, "candidate_generation_count": 0},
            retry_of_node_id=None,
            terminal_reason=action.reason,
            frontier_eligible=False,
            visibility_sequence=sequence,
            action_id="pending",
        )
        _commit_attempt(
            self._actions.record_node,
            RecordDiscoveryNodeRequest(
                node=stop,
                evaluation=None,
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"{self._world_id}:stop",
                requested_at=self._requested_at,
            ),
        )
        with OntologyUnitOfWork(self._engine) as uow:
            world = uow.discovery.world(self._world_id)
            nodes = uow.discovery.nodes_for_world(self._world_id)
        seal_hash = self._actions.seal_manifest(world, nodes)
        _committed(
            self._actions.seal_world(
                SealDiscoveryWorldRequest(
                    world_id=self._world_id,
                    terminal_reason=action.reason if action.selected_node_ids else "no_solution",
                    sealed_manifest_hash=seal_hash,
                    actor_id="sys:discovery",
                    actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                    idempotency_key=f"{self._world_id}:seal",
                    requested_at=self._requested_at,
                )
            )
        )
        self._terminal = True
        return TerminalObservation(action.reason, action.selected_node_ids)
