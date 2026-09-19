"""Isolated historical replay for the JCZQ ontology-v2 cutover gate."""

from __future__ import annotations

import hashlib
import json
import shutil
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
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_board_workflow import (
    JczqBoard,
    JczqBoardMatch,
    JczqBoardWorkflow,
    JczqResearchArtifact,
)

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
    board_count: int
    research_terminal_count: int
    research_status_counts: dict[str, int]
    missing_lineage: tuple[str, ...]
    odds_band_outcomes: tuple[str, ...]
    terminal_kind: str
    production_delta: dict[str, int]
    failures: tuple[str, ...]
    accepted: bool
    report_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_run_id": self.replay_run_id,
            "day": self.day,
            "schema_version": self.schema_version,
            "board_count": self.board_count,
            "research_terminal_count": self.research_terminal_count,
            "research_status_counts": dict(self.research_status_counts),
            "missing_lineage": list(self.missing_lineage),
            "odds_band_outcomes": list(self.odds_band_outcomes),
            "terminal_kind": self.terminal_kind,
            "production_delta": dict(self.production_delta),
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

        production_before = _tree_fingerprint(self._source_root / "ontology")
        production_counts_before = _production_counts(self._source_root / "ontology")
        day_root = self._copy_inputs(day)
        self._copy_ontology_if_needed()
        kernel = build_ontology_kernel(AppSettings(data_dir=self._isolated_root))
        kernel.initialize()

        board, board_failures = _load_board(
            day_root / "sporttery_markets.json",
            day,
            identity_path=day_root / "jczq-legs-base.json",
        )
        artifacts, artifact_failures = _load_research_artifacts(day_root, board)
        _seed_research_sources(kernel, artifacts)
        action_service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
        workflow = JczqBoardWorkflow(action_service)
        lineage_before = _lineage_snapshot(kernel, workflow, day)
        progress = workflow.intake_board(board, artifacts, historical_replay=True)

        missing_lineage, bands, terminal_kind = _lineage_status(
            kernel,
            workflow,
            day,
            before=lineage_before,
        )
        failures = tuple((*board_failures, *artifact_failures))
        if progress.total != len(board.matches):
            failures += ("board_research_terminal_count_mismatch",)
        if missing_lineage:
            failures += tuple(f"missing_lineage:{item}" for item in missing_lineage)
        if tuple(bands) != _REQUIRED_BANDS:
            failures += ("four_odds_band_outcomes_incomplete",)

        production_after = _tree_fingerprint(self._source_root / "ontology")
        production_counts_after = _production_counts(self._source_root / "ontology")
        production_delta = {
            key: production_counts_after[key] - production_counts_before[key]
            for key in _ZERO_DELTA
        }
        if production_after != production_before:
            failures += ("production_ontology_changed_during_replay",)
        if any(production_delta.values()):
            failures += ("production_side_effect_count_changed_during_replay",)

        accepted = not failures and terminal_kind in {"selected", "no_ticket"}
        payload: dict[str, object] = {
            "replay_run_id": _stable_id("jczq-replay", day, production_before),
            "day": day,
            "schema_version": kernel.status().schema_version,
            "board_count": len(board.matches),
            "research_terminal_count": progress.total,
            "research_status_counts": {
                "researched": progress.researched,
                "rejected": progress.rejected,
                "price_only": progress.price_only,
            },
            "missing_lineage": list(missing_lineage),
            "odds_band_outcomes": list(bands),
            "terminal_kind": terminal_kind,
            "production_delta": production_delta,
            "failures": list(failures),
            "accepted": accepted,
        }
        report_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        report = JczqReplayReport(
            replay_run_id=str(payload["replay_run_id"]),
            day=day,
            schema_version=int(payload["schema_version"]),
            board_count=len(board.matches),
            research_terminal_count=progress.total,
            research_status_counts=dict(payload["research_status_counts"]),
            missing_lineage=missing_lineage,
            odds_band_outcomes=bands,
            terminal_kind=terminal_kind,
            production_delta=production_delta,
            failures=failures,
            accepted=accepted,
            report_sha256=report_hash,
        )
        output = self._isolated_root / f"replay-{day}.json"
        output.write_text(canonical_json(report.to_dict()) + "\n", encoding="utf-8")
        return report

    def _copy_inputs(self, day: str) -> Path:
        source = self._source_root / "jczq" / "daily" / day
        if not source.is_dir():
            raise ValueError(f"JCZQ source day is missing: {day}")
        destination = self._isolated_root / "jczq" / "daily" / day
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return destination

    def _copy_ontology_if_needed(self) -> None:
        source = self._source_root / "ontology"
        destination = self._isolated_root / "ontology"
        if destination.exists() or not source.exists():
            return
        shutil.copytree(source, destination)


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
            else _stable_id(
                "replay-artifact", board.business_date, path.name, _sha256(data)
            )
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


def _seed_research_sources(kernel, artifacts: tuple[JczqResearchArtifact, ...]) -> None:
    with kernel.engine.begin() as connection:
        for artifact in artifacts:
            if (
                artifact.captured_at is None
                or artifact.source_run_id is None
                or artifact.artifact_id is None
            ):
                continue
            connection.execute(
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
            connection.execute(
                insert(schema.source_artifacts).prefix_with("OR IGNORE").values(
                    artifact_id=artifact.artifact_id,
                    first_recorded_at=artifact.captured_at.isoformat(),
                    content_type="application/json",
                    storage_path=artifact.artifact_path,
                    byte_size=len(artifact.artifact_bytes or b""),
                    content_hash=_sha256(artifact.artifact_bytes or b""),
                )
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
