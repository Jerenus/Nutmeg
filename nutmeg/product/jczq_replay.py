"""Isolated historical replay for the JCZQ ontology-v2 cutover gate."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import insert

from nutmeg.config.settings import AppSettings
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.actions.replay_actions import (
    FinishHistoricalReplayRequest,
    ReplayActions,
    StartHistoricalReplayRequest,
)
from nutmeg.ontology.actions.service import ActionService, ReplayActionContext
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.artifacts import ArtifactRetrievalRow
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_board_workflow import (
    JczqBoard,
    JczqBoardMatch,
    JczqBoardWorkflow,
    JczqResearchArtifact,
)
from nutmeg.product.jczq_replay_adjudication import (
    ReplayAdjudicationInput,
    ReplayAdjudicator,
)
from nutmeg.product.jczq_replay_inputs import ReplayInputManifest, freeze_replay_inputs
from nutmeg.product.jczq_replay_workflow import run_replay_results, run_replay_workflow

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ZERO_DELTA = MappingProxyType(
    {
        "objects": 0,
        "money_entries": 0,
        "dispatches": 0,
        "prospective_observations": 0,
    }
)
_REQUIRED_BANDS = ("10x", "20x", "50x", "100x")


def _stable_id(kind: str, *parts: object) -> str:
    payload = canonical_json([kind, *parts])
    return f"{kind}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class JczqReplayReport:
    replay_run_id: str
    day: str
    schema_version: int
    run_status: str
    source_manifest_hash: str
    isolated_database_identity: str
    board_count: int
    research_terminal_count: int
    research_status_counts: dict[str, int]
    missing_lineage: tuple[str, ...]
    odds_band_outcomes: tuple[str, ...]
    replay_action_counts: dict[str, int]
    adjudication_branch_counts: dict[str, int]
    committed_forecast_count: int
    evidence_lineage_count: int
    judgment_prescription_revision_id: str | None
    candidate_set_revision_ids: tuple[str, ...]
    structured_band_outcomes: tuple[dict[str, object], ...]
    audit_complete: bool
    terminal_kind: str
    no_ticket_revision_id: str | None
    authoritative_result_count: int
    replay_prediction_count: int
    replay_score_count: int
    rsi_statuses: dict[str, str]
    quarantined_gaps: tuple[str, ...]
    production_before_fingerprint: str
    production_after_fingerprint: str
    production_delta: dict[str, int]
    protected_replay_counts: dict[str, int]
    failures: tuple[str, ...]
    accepted: bool
    report_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_run_id": self.replay_run_id,
            "day": self.day,
            "schema_version": self.schema_version,
            "run_status": self.run_status,
            "source_manifest_hash": self.source_manifest_hash,
            "isolated_database_identity": self.isolated_database_identity,
            "board_count": self.board_count,
            "research_terminal_count": self.research_terminal_count,
            "research_status_counts": dict(self.research_status_counts),
            "missing_lineage": list(self.missing_lineage),
            "odds_band_outcomes": list(self.odds_band_outcomes),
            "replay_action_counts": dict(self.replay_action_counts),
            "adjudication_branch_counts": dict(self.adjudication_branch_counts),
            "committed_forecast_count": self.committed_forecast_count,
            "evidence_lineage_count": self.evidence_lineage_count,
            "judgment_prescription_revision_id": (
                self.judgment_prescription_revision_id
            ),
            "candidate_set_revision_ids": list(self.candidate_set_revision_ids),
            "structured_band_outcomes": [
                dict(outcome) for outcome in self.structured_band_outcomes
            ],
            "audit_complete": self.audit_complete,
            "terminal_kind": self.terminal_kind,
            "no_ticket_revision_id": self.no_ticket_revision_id,
            "authoritative_result_count": self.authoritative_result_count,
            "replay_prediction_count": self.replay_prediction_count,
            "replay_score_count": self.replay_score_count,
            "rsi_statuses": dict(self.rsi_statuses),
            "quarantined_gaps": list(self.quarantined_gaps),
            "production_before_fingerprint": self.production_before_fingerprint,
            "production_after_fingerprint": self.production_after_fingerprint,
            "production_delta": dict(self.production_delta),
            "protected_replay_counts": dict(self.protected_replay_counts),
            "failures": list(self.failures),
            "accepted": self.accepted,
            "report_sha256": self.report_sha256,
        }


class JczqReplayRunner:
    """Rebuild replay-owned state without opening the production store for writes."""

    def __init__(self, *, source_root: Path, isolated_root: Path) -> None:
        self._source_root = Path(source_root).expanduser().resolve()
        self._isolated_root = Path(isolated_root).expanduser().resolve()

    def run(self, day: str) -> JczqReplayReport:
        production_db = (self._source_root / "ontology" / "ontology.db").resolve()
        isolated_db = (self._isolated_root / "ontology" / "ontology.db").resolve()
        if isolated_db == production_db:
            raise ValueError("isolated ontology path equals production ontology path")

        production_counts_before = _production_counts(self._source_root / "ontology")
        production_before = _tree_fingerprint(self._source_root / "ontology")
        manifest = self._copy_inputs(day)
        manifest.verify()
        day_root = Path(manifest.root)
        kernel = build_ontology_kernel(AppSettings(data_dir=self._isolated_root))
        kernel.initialize()
        replay_run_id = _stable_id(
            "jczq-replay", day, production_before, manifest.manifest_hash
        )
        base_action_service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
        ReplayActions(base_action_service).start(
            StartHistoricalReplayRequest(
                replay_run_id=replay_run_id,
                business_date=day,
                source_root_fingerprint=_tree_fingerprint(
                    self._source_root / "jczq" / "daily" / day
                ),
                source_manifest_hash=manifest.manifest_hash,
                isolated_database_identity=str(isolated_db),
                production_database_identity=str(production_db),
                schema_version=kernel.status().schema_version,
                production_before={
                    "tree_fingerprint": production_before,
                    "protected_counts": production_counts_before,
                },
                idempotency_key=f"historical-replay:start:{replay_run_id}",
                requested_at=datetime.now(_SHANGHAI),
            )
        )

        board, board_failures = _load_board(
            day_root / "sporttery_markets.json",
            day,
            identity_path=day_root / "jczq-legs-base.json",
        )
        artifacts, artifact_failures = _load_research_artifacts(day_root, board)
        with OntologyUnitOfWork(kernel.engine) as uow:
            for match in board.matches:
                uow.identity.insert_match_minimal(match.match_id)
        observation_ids = _seed_research_sources(kernel, artifacts)
        observation_ids.update(
            _seed_official_market_observations(
                kernel,
                replay_run_id=replay_run_id,
                board=board,
                day_root=day_root,
                manifest=manifest,
                existing_observation_ids=observation_ids,
            )
        )
        action_service = base_action_service.bind_replay(
            ReplayActionContext(replay_run_id, day, str(isolated_db))
        )
        workflow = JczqBoardWorkflow(action_service)
        lineage_before = _lineage_snapshot(kernel, workflow, day)
        progress = workflow.intake_board(board, artifacts, historical_replay=True)
        _run_replay_adjudication(
            action_service,
            replay_run_id=replay_run_id,
            board=board,
            day_root=day_root,
            manifest=manifest,
            kernel=kernel,
            observation_ids=observation_ids,
        )
        run_replay_workflow(
            action_service,
            kernel=kernel,
            replay_run_id=replay_run_id,
            day=day,
            day_root=day_root,
            manifest=manifest,
            board=board,
            observation_ids=observation_ids,
        )
        run_replay_results(
            action_service,
            kernel=kernel,
            replay_run_id=replay_run_id,
            day_root=day_root,
            manifest=manifest,
            board=board,
        )

        missing_lineage, bands, terminal_kind = _lineage_status(
            kernel,
            workflow,
            day,
            before=lineage_before,
        )
        metrics = _derive_replay_metrics(isolated_db, replay_run_id)
        failures = tuple((*board_failures, *artifact_failures))
        if progress.total != len(board.matches):
            failures += ("board_research_terminal_count_mismatch",)
        if missing_lineage:
            failures += tuple(f"missing_lineage:{item}" for item in missing_lineage)
        if tuple(bands) != _REQUIRED_BANDS:
            failures += ("four_odds_band_outcomes_incomplete",)
        if metrics["committed_forecast_count"] != len(board.matches):
            failures += ("committed_forecast_coverage_incomplete",)
        if metrics["evidence_lineage_count"] != len(board.matches):
            failures += ("forecast_evidence_lineage_incomplete",)
        if len(metrics["structured_band_outcomes"]) != 2 * len(_REQUIRED_BANDS):
            failures += ("structured_band_outcomes_incomplete",)
        if metrics["authoritative_result_count"] != len(board.matches):
            failures += ("authoritative_results_missing",)
        if metrics["replay_prediction_count"] != len(board.matches):
            failures += ("replay_prediction_coverage_incomplete",)
        if metrics["replay_score_count"] != len(board.matches):
            failures += ("replay_score_coverage_incomplete",)
        if any(metrics["protected_replay_counts"].values()):
            failures += ("protected_replay_side_effect_detected",)

        production_counts_after = _production_counts(self._source_root / "ontology")
        production_after = _tree_fingerprint(self._source_root / "ontology")
        production_delta = {
            key: production_counts_after[key] - production_counts_before[key]
            for key in _ZERO_DELTA
        }
        if production_after != production_before:
            failures += ("production_ontology_changed_during_replay",)
        if any(production_delta.values()):
            failures += ("production_side_effect_count_changed_during_replay",)

        accepted = not failures and terminal_kind == "no_ticket"
        run_status = "accepted" if accepted else "failed"
        rsi_statuses = {
            experiment: (
                "replay_excluded" if metrics["authoritative_result_count"] else "replay_gap"
            )
            for experiment in ("R0", "F5", "F9")
        }
        quarantined_gaps = tuple(
            f"{item.relative_path}:{item.reason}" for item in manifest.quarantined
        )
        payload: dict[str, object] = {
            "replay_run_id": replay_run_id,
            "day": day,
            "schema_version": kernel.status().schema_version,
            "run_status": run_status,
            "source_manifest_hash": manifest.manifest_hash,
            "isolated_database_identity": str(isolated_db),
            "board_count": len(board.matches),
            "research_terminal_count": progress.total,
            "research_status_counts": {
                "researched": progress.researched,
                "rejected": progress.rejected,
                "price_only": progress.price_only,
            },
            "missing_lineage": list(missing_lineage),
            "odds_band_outcomes": list(bands),
            "replay_action_counts": metrics["replay_action_counts"],
            "adjudication_branch_counts": metrics["adjudication_branch_counts"],
            "committed_forecast_count": metrics["committed_forecast_count"],
            "evidence_lineage_count": metrics["evidence_lineage_count"],
            "judgment_prescription_revision_id": metrics[
                "judgment_prescription_revision_id"
            ],
            "candidate_set_revision_ids": metrics["candidate_set_revision_ids"],
            "structured_band_outcomes": metrics["structured_band_outcomes"],
            "audit_complete": metrics["audit_complete"],
            "terminal_kind": terminal_kind,
            "no_ticket_revision_id": metrics["no_ticket_revision_id"],
            "authoritative_result_count": metrics["authoritative_result_count"],
            "replay_prediction_count": metrics["replay_prediction_count"],
            "replay_score_count": metrics["replay_score_count"],
            "rsi_statuses": rsi_statuses,
            "quarantined_gaps": list(quarantined_gaps),
            "production_before_fingerprint": production_before,
            "production_after_fingerprint": production_after,
            "production_delta": production_delta,
            "protected_replay_counts": metrics["protected_replay_counts"],
            "failures": list(failures),
            "accepted": accepted,
        }
        report_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        ReplayActions(base_action_service).finish(
            FinishHistoricalReplayRequest(
                replay_run_id=replay_run_id,
                business_date=day,
                isolated_database_identity=str(isolated_db),
                status=run_status,
                production_after={
                    "tree_fingerprint": production_after,
                    "protected_counts": production_counts_after,
                },
                report_sha256=report_hash,
                failure_codes=failures,
                idempotency_key=f"historical-replay:finish:{replay_run_id}",
                requested_at=datetime.now(_SHANGHAI),
            )
        )
        report = JczqReplayReport(
            replay_run_id=str(payload["replay_run_id"]),
            day=day,
            schema_version=int(payload["schema_version"]),
            run_status=run_status,
            source_manifest_hash=manifest.manifest_hash,
            isolated_database_identity=str(isolated_db),
            board_count=len(board.matches),
            research_terminal_count=progress.total,
            research_status_counts=dict(payload["research_status_counts"]),
            missing_lineage=missing_lineage,
            odds_band_outcomes=bands,
            replay_action_counts=dict(metrics["replay_action_counts"]),
            adjudication_branch_counts=dict(metrics["adjudication_branch_counts"]),
            committed_forecast_count=int(metrics["committed_forecast_count"]),
            evidence_lineage_count=int(metrics["evidence_lineage_count"]),
            judgment_prescription_revision_id=metrics[
                "judgment_prescription_revision_id"
            ],
            candidate_set_revision_ids=tuple(metrics["candidate_set_revision_ids"]),
            structured_band_outcomes=tuple(metrics["structured_band_outcomes"]),
            audit_complete=bool(metrics["audit_complete"]),
            terminal_kind=terminal_kind,
            no_ticket_revision_id=metrics["no_ticket_revision_id"],
            authoritative_result_count=int(metrics["authoritative_result_count"]),
            replay_prediction_count=int(metrics["replay_prediction_count"]),
            replay_score_count=int(metrics["replay_score_count"]),
            rsi_statuses=rsi_statuses,
            quarantined_gaps=quarantined_gaps,
            production_before_fingerprint=production_before,
            production_after_fingerprint=production_after,
            production_delta=production_delta,
            protected_replay_counts=dict(metrics["protected_replay_counts"]),
            failures=failures,
            accepted=accepted,
            report_sha256=report_hash,
        )
        output = self._isolated_root / f"replay-{day}.json"
        output.write_text(canonical_json(report.to_dict()) + "\n", encoding="utf-8")
        return report

    def _copy_inputs(self, day: str) -> ReplayInputManifest:
        source = self._source_root / "jczq" / "daily" / day
        if not source.is_dir():
            raise ValueError(f"JCZQ source day is missing: {day}")
        destination = self._isolated_root / "jczq" / "daily" / day
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = freeze_replay_inputs(source, destination)
        manifest_path = self._isolated_root / f"replay-input-manifest-{day}.json"
        manifest_path.write_text(
            canonical_json(manifest.to_dict()) + "\n",
            encoding="utf-8",
        )
        return manifest


def _tree_fingerprint(root: Path) -> str:
    if not root.exists():
        return "missing"
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _production_counts(root: Path) -> dict[str, int]:
    database = root / "ontology.db"
    if not database.is_file():
        return dict(_ZERO_DELTA)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        objects = sum(
            int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in table_names
        )

        def count(table: str, where: str = "") -> int:
            if table not in table_names:
                return 0
            return int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}" {where}').fetchone()[
                    0
                ]
            )

        return {
            "objects": objects,
            "money_entries": count("cash_transactions"),
            "dispatches": count("outbox_events"),
            "prospective_observations": count(
                "rsi_observations", "WHERE prospective = 1"
            ),
        }
    finally:
        connection.close()


def _derive_replay_metrics(database: Path, replay_run_id: str) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        action_counts = {
            str(row["action_type"]): int(row["count"])
            for row in connection.execute(
                "SELECT action_type, COUNT(*) AS count FROM actions "
                "WHERE historical_replay = 1 AND replay_run_id = ? "
                "AND action_type != 'finish_historical_replay' "
                "GROUP BY action_type ORDER BY action_type",
                (replay_run_id,),
            )
        }
        branch_counts = {branch: 0 for branch in ("approve", "revise", "reject")}
        for row in connection.execute(
            "SELECT decision, COUNT(*) AS count FROM adjudications "
            "WHERE decision IN ('approve', 'revise', 'reject') "
            "GROUP BY decision"
        ):
            branch_counts[str(row["decision"])] = int(row["count"])

        current_forecasts = """
            SELECT forecast_revision_id, forecast_series_id, evidence_bundle_id
            FROM forecast_revisions AS current
            WHERE status = 'committed'
              AND NOT EXISTS (
                SELECT 1 FROM forecast_revisions AS newer
                WHERE newer.forecast_series_id = current.forecast_series_id
                  AND newer.revision_no > current.revision_no
              )
        """
        committed_forecast_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM ({current_forecasts})"
            ).fetchone()[0]
        )
        evidence_lineage_count = int(
            connection.execute(
                f"""
                SELECT COUNT(DISTINCT forecasts.forecast_series_id)
                FROM ({current_forecasts}) AS forecasts
                JOIN evidence_bundle_items AS items
                  ON items.evidence_bundle_id = forecasts.evidence_bundle_id
                JOIN observation_sources AS sources
                  ON sources.observation_id = items.observation_id
                JOIN artifact_retrievals AS retrievals
                  ON retrievals.artifact_retrieval_id = sources.artifact_retrieval_id
                JOIN source_runs AS runs
                  ON runs.source_run_id = retrievals.source_run_id
                WHERE runs.status = 'succeeded'
                """
            ).fetchone()[0]
        )
        prescription_row = connection.execute(
            "SELECT judgment_prescription_revision_id "
            "FROM operator_judgment_prescription_revisions "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        candidate_set_rows = tuple(
            connection.execute(
                "SELECT candidate_set_revision_id, set_kind "
                "FROM operator_candidate_set_revisions ORDER BY set_kind"
            ).fetchall()
        )
        structured_band_outcomes = tuple(
            {
                "candidate_set_revision_id": str(row["candidate_set_revision_id"]),
                "set_kind": str(row["set_kind"]),
                "odds_band": str(row["odds_band"]),
                "status": str(row["status"]),
                "candidate_count": int(row["candidate_count"]),
                "reason_code": row["reason_code"],
            }
            for row in connection.execute(
                "SELECT sets.candidate_set_revision_id, sets.set_kind, "
                "bands.odds_band, bands.status, bands.candidate_count, "
                "bands.reason_code FROM operator_candidate_band_outcomes AS bands "
                "JOIN operator_candidate_set_revisions AS sets "
                "ON sets.candidate_set_revision_id = bands.candidate_set_revision_id "
                "ORDER BY sets.set_kind, bands.odds_band"
            )
        )
        no_ticket_row = connection.execute(
            "SELECT no_ticket_revision_id FROM operator_no_ticket_revisions "
            "WHERE deployment_outcome = 'no_ticket' ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()

        def count(table: str, where: str = "", parameters: tuple[object, ...] = ()) -> int:
            return int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" {where}', parameters
                ).fetchone()[0]
            )

        protected_counts = {
            "ticket_placements": count("ticket_placements"),
            "cash_transactions": count("cash_transactions"),
            "ticket_confirmations": count("ticket_confirmation_challenges"),
            "rsi_observations": count("rsi_observations"),
            "rsi_grades": count("rsi_grades"),
            "rsi_verdicts": count("rsi_verdicts"),
            "rsi_deployments": count("rsi_deployments"),
        }
        return {
            "replay_action_counts": action_counts,
            "adjudication_branch_counts": branch_counts,
            "committed_forecast_count": committed_forecast_count,
            "evidence_lineage_count": evidence_lineage_count,
            "judgment_prescription_revision_id": (
                None if prescription_row is None else str(prescription_row[0])
            ),
            "candidate_set_revision_ids": tuple(
                str(row["set_kind"]) for row in candidate_set_rows
            ),
            "structured_band_outcomes": structured_band_outcomes,
            "audit_complete": (
                len(candidate_set_rows) == 2
                and len(structured_band_outcomes) == 2 * len(_REQUIRED_BANDS)
            ),
            "no_ticket_revision_id": (
                None if no_ticket_row is None else str(no_ticket_row[0])
            ),
            "authoritative_result_count": count("match_outcomes"),
            "replay_prediction_count": count("predictions"),
            "replay_score_count": count(
                "predictions",
                "WHERE status IN ('confirmed', 'refuted') AND outcome IS NOT NULL",
            ),
            "protected_replay_counts": protected_counts,
        }
    finally:
        connection.close()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid replay input: {path.name}") from error


def _load_board(
    path: Path,
    day: str,
    *,
    identity_path: Path | None = None,
) -> tuple[JczqBoard, tuple[str, ...]]:
    document = _load_json(path)
    if not isinstance(document, dict):
        raise ValueError("sporttery market board must be an object")
    groups = document.get("matchInfoList")
    if not isinstance(groups, list):
        raise ValueError("sporttery market board has no matchInfoList")
    matching_groups = [
        group
        for group in groups
        if isinstance(group, dict) and group.get("businessDate") == day
    ]
    if not matching_groups:
        raise ValueError(f"sporttery market board has no business date {day}")
    rows = [
        row
        for group in matching_groups
        for row in group.get("subMatchList", [])
        if isinstance(row, dict) and row.get("businessDate", day) == day
    ]
    unique_rows: dict[str, dict[str, object]] = {}
    for row in rows:
        identity = str(row.get("matchId") or row.get("matchNumStr") or "")
        if identity:
            unique_rows.setdefault(identity, row)
    failures: list[str] = []
    canonical_ids: dict[str, str] = {}
    if identity_path is not None and identity_path.is_file():
        identity_document = _load_json(identity_path)
        if isinstance(identity_document, dict):
            legs = identity_document.get("legs")
            if isinstance(legs, dict):
                canonical_ids = {
                    str(code): str(leg["match_id"])
                    for code, leg in legs.items()
                    if isinstance(leg, dict)
                    and isinstance(leg.get("match_id"), str)
                    and str(leg["match_id"]).strip()
                }
    matches: list[JczqBoardMatch] = []
    for row in unique_rows.values():
        official_no = row.get("matchNumStr")
        match_id = row.get("matchId")
        match_date = row.get("matchDate") or day
        match_time = row.get("matchTime")
        if not official_no or match_id is None or not match_time:
            failures.append("board_match_identity_or_kickoff_missing")
            continue
        kickoff = datetime.fromisoformat(f"{match_date}T{match_time}").replace(
            tzinfo=_SHANGHAI
        )
        matches.append(
            JczqBoardMatch(
                match_id=canonical_ids.get(
                    str(official_no), f"jczq-sporttery-{match_id}"
                ),
                official_match_no=str(official_no),
                kickoff_at=kickoff,
            )
        )
    matches.sort(key=lambda item: item.official_match_no)
    return JczqBoard(business_date=day, matches=tuple(matches)), tuple(failures)


def _load_research_artifacts(
    day_root: Path,
    board: JczqBoard,
) -> tuple[tuple[JczqResearchArtifact, ...], tuple[str, ...]]:
    artifacts: list[JczqResearchArtifact] = []
    failures: list[str] = []
    for match in board.matches:
        accepted = day_root / f"research-{match.official_match_no}.json"
        rejected = day_root / f"research-{match.official_match_no}.rejected.json"
        path = rejected if rejected.exists() else accepted
        if not path.exists():
            continue
        document = _load_json(path)
        if not isinstance(document, dict):
            failures.append(f"research_document_invalid:{match.official_match_no}")
            continue
        data = path.read_bytes()
        captured_text = document.get("captured_at")
        captured_at = None
        if not isinstance(captured_text, str):
            if path != rejected:
                failures.append(f"research_capture_time_missing:{match.official_match_no}")
        else:
            captured_at = datetime.fromisoformat(captured_text)
            if captured_at.tzinfo is None:
                failures.append(f"research_capture_time_naive:{match.official_match_no}")
                captured_at = None
        rejected_input = path == rejected
        if captured_at is None and not rejected_input:
            continue
        artifact_id = (
            None
            if captured_at is None
            else _stable_id("replay-artifact", _sha256(data))
        )
        artifacts.append(
            JczqResearchArtifact(
                match_id=match.match_id,
                captured_at=captured_at,
                source_run_id=(
                    None
                    if captured_at is None
                    else _stable_id("replay-source", board.business_date, path.name)
                ),
                artifact_id=artifact_id,
                intake_errors=(
                    ("historical_research_rejected",) if rejected_input else ()
                ),
                artifact_path=str(path),
                artifact_bytes=data,
            )
        )
    return tuple(artifacts), tuple(failures)


def _seed_research_sources(
    kernel, artifacts: tuple[JczqResearchArtifact, ...]
) -> dict[str, str]:
    observation_ids: dict[str, str] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for artifact in artifacts:
            if (
                artifact.captured_at is None
                or artifact.source_run_id is None
                or artifact.artifact_id is None
            ):
                continue
            uow.connection.execute(
                insert(schema.source_runs).prefix_with("OR IGNORE").values(
                    source_run_id=artifact.source_run_id,
                    source_name="jczq_historical_replay",
                    source_type="credible_media",
                    started_at=artifact.captured_at.isoformat(),
                    finished_at=artifact.captured_at.isoformat(),
                    status="succeeded",
                    error_code=None,
                    error_detail=None,
                )
            )
            uow.connection.execute(
                insert(schema.source_artifacts).prefix_with("OR IGNORE").values(
                    artifact_id=artifact.artifact_id,
                    first_recorded_at=artifact.captured_at.isoformat(),
                    content_type="application/json",
                    storage_path=artifact.artifact_path,
                    byte_size=len(artifact.artifact_bytes or b""),
                    content_hash=_sha256(artifact.artifact_bytes or b""),
                )
            )
            retrieval_id = _stable_id(
                "replay-retrieval",
                artifact.artifact_id,
                artifact.source_run_id,
            )
            uow.artifacts.insert_retrieval(
                ArtifactRetrievalRow(
                    artifact_retrieval_id=retrieval_id,
                    artifact_id=artifact.artifact_id,
                    source_run_id=artifact.source_run_id,
                    source_name="jczq_historical_replay",
                    source_type="credible_media",
                    reported_content_type="application/json",
                    canonical_url=None,
                    requested_url=None,
                    published_at=artifact.captured_at.isoformat(),
                    retrieved_at=artifact.captured_at.isoformat(),
                    status="stored",
                )
            )
            observation_id = _stable_id(
                "replay-observation",
                artifact.match_id,
                retrieval_id,
            )
            uow.evidence.insert_observation(
                ObservationRow(
                    observation_id=observation_id,
                    observation_type="historical_research",
                    subject_type="match",
                    subject_id=artifact.match_id,
                    scope_match_id=artifact.match_id,
                    value={"historical_replay": True},
                    schema_version="1",
                    valid_from=artifact.captured_at.isoformat(),
                    valid_to=None,
                    observed_at=artifact.captured_at.isoformat(),
                    recorded_at=artifact.captured_at.isoformat(),
                    verification_method=VerificationMethod.CORROBORATED.value,
                    quality={},
                ),
                (retrieval_id,),
            )
            observation_ids[artifact.match_id] = observation_id
    return observation_ids


def _seed_official_market_observations(
    kernel,
    *,
    replay_run_id: str,
    board: JczqBoard,
    day_root: Path,
    manifest: ReplayInputManifest,
    existing_observation_ids: dict[str, str],
) -> dict[str, str]:
    entry = manifest.entry("sporttery_markets.json")
    if entry.semantic_timestamp is None:
        raise ValueError("official market update time is missing")
    observed_at = _aware_semantic_time(entry.semantic_timestamp).isoformat()
    source_run_id = _stable_id("replay-market-source", replay_run_id)
    artifact_id = _stable_id("replay-artifact", entry.sha256)
    retrieval_id = _stable_id("replay-market-retrieval", replay_run_id)
    board_path = day_root / "sporttery_markets.json"
    board_bytes = board_path.read_bytes()
    seeded: dict[str, str] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.connection.execute(
            insert(schema.source_runs).prefix_with("OR IGNORE").values(
                source_run_id=source_run_id,
                source_name="sporttery_historical_replay",
                source_type="official_sale_schedule",
                started_at=observed_at,
                finished_at=observed_at,
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        uow.connection.execute(
            insert(schema.source_artifacts).prefix_with("OR IGNORE").values(
                artifact_id=artifact_id,
                first_recorded_at=observed_at,
                content_type="application/json",
                storage_path=str(board_path),
                byte_size=len(board_bytes),
                content_hash=entry.sha256,
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
                published_at=observed_at,
                retrieved_at=observed_at,
                status="stored",
            )
        )
        for match in board.matches:
            if match.match_id in existing_observation_ids:
                continue
            observation_id = _stable_id(
                "replay-market-observation", replay_run_id, match.match_id
            )
            uow.evidence.insert_observation(
                ObservationRow(
                    observation_id=observation_id,
                    observation_type="official_market_anchor",
                    subject_type="match",
                    subject_id=match.match_id,
                    scope_match_id=match.match_id,
                    value={"historical_replay": True, "market_anchor": True},
                    schema_version="1",
                    valid_from=observed_at,
                    valid_to=None,
                    observed_at=observed_at,
                    recorded_at=observed_at,
                    verification_method=VerificationMethod.OFFICIAL.value,
                    quality={},
                ),
                (retrieval_id,),
            )
            seeded[match.match_id] = observation_id
    return seeded


def _aware_semantic_time(value: str) -> datetime:
    normalized = value.replace(" ", "T")
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=_SHANGHAI) if parsed.tzinfo is None else parsed


def _run_replay_adjudication(
    action_service: ActionService,
    *,
    replay_run_id: str,
    board: JczqBoard,
    day_root: Path,
    manifest: ReplayInputManifest,
    kernel,
    observation_ids: dict[str, str],
) -> None:
    reads = _load_json(day_root / "reads.json")
    if not isinstance(reads, list) or len(reads) != len(board.matches):
        raise ValueError("historical replay Reads do not cover the board")
    market_time_text = manifest.entry("sporttery_markets.json").semantic_timestamp
    if market_time_text is None:
        raise ValueError("official market update time is missing")
    market_time = _aware_semantic_time(market_time_text)
    by_match_id = {match.match_id: match for match in board.matches}
    prepared: list[ReplayAdjudicationInput] = []
    with OntologyUnitOfWork(kernel.engine) as uow:
        for index, raw in enumerate(reads):
            if not isinstance(raw, dict):
                raise ValueError("historical replay Read must be an object")
            match = by_match_id.get(str(raw.get("match_id"))) or board.matches[index]
            made_at = datetime.fromisoformat(str(raw["made_at"]))
            prior = {
                str(key): float(value)
                for key, value in dict(
                    raw.get("prior")
                    or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
                ).items()
            }
            belief = {
                str(key): float(value)
                for key, value in dict(raw.get("belief") or prior).items()
            }
            snapshot_id = _stable_id(
                "replay-market-snapshot", replay_run_id, match.match_id
            )
            uow.market.insert_snapshot(
                SnapshotRow(
                    market_snapshot_id=snapshot_id,
                    match_id=match.match_id,
                    market_definition_id="md-had",
                    snapshot_kind="historical_replay_cutoff",
                    as_of=market_time.isoformat(),
                    fair_distribution=prior,
                    devig_method="source_read_prior",
                    method_version="1",
                    source_coverage={"manifest": manifest.manifest_hash},
                    freshness={},
                    disagreement={},
                )
            )
            observation_id = observation_ids.get(match.match_id)
            citations = (
                ({"object_type": "observation", "object_id": observation_id},)
                if observation_id is not None
                else ({"object_type": "market_snapshot", "object_id": snapshot_id},)
            )
            branch = "reject" if index == 0 else "revise" if index == 1 else "approve"
            prepared.append(
                ReplayAdjudicationInput(
                    read_id=str(raw.get("read_id") or f"read-{index + 1}"),
                    match_id=match.match_id,
                    made_at=made_at,
                    origin=str(raw.get("judge") or "historical-read"),
                    branch=branch,
                    reason=f"historical replay fixture branch: {branch}",
                    market_definition_id="md-had",
                    market_snapshot_id=snapshot_id,
                    prior_distribution=prior,
                    belief_distribution=belief,
                    revised_belief_distribution=prior,
                    citation_refs=citations,
                    candidate_observation_ids=(
                        () if observation_id is None else (observation_id,)
                    ),
                )
            )
    ReplayAdjudicator(action_service, replay_run_id=replay_run_id).adjudicate(
        tuple(prepared)
    )


@dataclass(frozen=True, slots=True)
class _LineageSnapshot:
    committed_forecasts: int
    candidate_sets: int
    candidate_audits: int
    bands: frozenset[str]
    terminal_kind: str


def _lineage_snapshot(kernel, workflow, day: str) -> _LineageSnapshot:
    database = kernel.paths.database
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        committed_forecasts = connection.execute(
            "SELECT COUNT(*) FROM forecast_revisions WHERE status = 'committed' "
            "AND substr(made_at, 1, 10) = ?",
            (day,),
        ).fetchone()[0]
        candidate_sets = connection.execute(
            "SELECT COUNT(*) FROM operator_candidate_set_revisions "
            "WHERE substr(created_at, 1, 10) = ?",
            (day,),
        ).fetchone()[0]
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM operator_candidate_audit_findings"
        ).fetchone()[0]
        bands = frozenset(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT odds_band FROM operator_candidate_band_outcomes"
            ).fetchall()
        )
    finally:
        connection.close()

    try:
        terminal_kind = workflow.require_terminal_state(day).kind
    except ValueError:
        terminal_kind = "missing"
    return _LineageSnapshot(
        committed_forecasts=committed_forecasts,
        candidate_sets=candidate_sets,
        candidate_audits=audit_count,
        bands=bands,
        terminal_kind=terminal_kind,
    )


def _lineage_status(
    kernel,
    workflow,
    day: str,
    *,
    before: _LineageSnapshot,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    after = _lineage_snapshot(kernel, workflow, day)
    new_bands = tuple(band for band in _REQUIRED_BANDS if band in after.bands - before.bands)
    terminal_kind = (
        after.terminal_kind
        if before.terminal_kind == "missing" and after.terminal_kind != "missing"
        else "missing"
    )
    missing: list[str] = []
    if after.committed_forecasts <= before.committed_forecasts:
        missing.append("committed_forecast_revisions")
    if after.candidate_sets - before.candidate_sets < 2:
        missing.append("candidate_set_revisions")
    if after.candidate_audits <= before.candidate_audits:
        missing.append("candidate_audits")
    if terminal_kind == "missing":
        missing.append("terminal_decision")
    return tuple(missing), new_bands, terminal_kind


__all__ = ["JczqReplayReport", "JczqReplayRunner"]
