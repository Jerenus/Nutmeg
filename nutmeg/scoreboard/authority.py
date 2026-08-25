"""Exact-hash shadow review, cutover gates, and compatibility export."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from sqlalchemy import select, text

from nutmeg.analytics.high_watermark import high_watermark
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.actions.scoreboard_actions import (
    ApproveScoreboardCutoverRequest,
    RecordScoreboardExportRequest,
    RecordScoreboardShadowReviewRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.storage.duckdb_utils import connect_analytics_db

_SOP_FILENAMES = {
    "CONSTITUTION.md",
    "RUNBOOK.md",
    "RULEBOOK.md",
    "AGENTS.md",
    "CLAUDE.md",
}
_SOP_STATEMENTS = (
    "scoreboard authority: ontology",
    "scoreboard.json: generated read-only compatibility output",
    "reconcile/calibrate rebuilds and exports scoreboard.json",
    "manual facts: RecordScoreboardObservation",
    "direct scoreboard.json edits are errors",
)
_CLASSIFICATIONS = {
    "matched",
    "formal_manual",
    "source_correction",
    "unexplained",
}


class ScoreboardAuthorityError(RuntimeError):
    """A scoreboard authority precondition is not satisfied."""


class ScoreboardExportDriftError(ScoreboardAuthorityError):
    """Compatibility output differs from its recorded export hash."""


@dataclass(frozen=True, slots=True)
class SopAuthorityReport:
    ready: bool
    missing_by_path: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ProjectionIdentity:
    version: str
    source_high_watermark: int
    built_at: str
    cohort_definition_version: str
    metric_version: str


@dataclass(frozen=True, slots=True)
class ScoreboardExportResult:
    path: Path
    sha256: str
    action_id: str


def check_sop_authority(paths: list[Path]) -> SopAuthorityReport:
    resolved = {Path(path).name: Path(path) for path in paths}
    missing_by_path: dict[str, tuple[str, ...]] = {}
    for filename in sorted(_SOP_FILENAMES):
        path = resolved.get(filename)
        if path is None or not path.is_file():
            missing_by_path[str(path or filename)] = _SOP_STATEMENTS
            continue
        text = path.read_text(encoding="utf-8")
        missing = tuple(statement for statement in _SOP_STATEMENTS if statement not in text)
        if missing:
            missing_by_path[str(path)] = missing
    extras = set(resolved) - _SOP_FILENAMES
    for filename in sorted(extras):
        missing_by_path[str(resolved[filename])] = ("unexpected authority document",)
    return SopAuthorityReport(ready=not missing_by_path, missing_by_path=missing_by_path)


def atomic_write(destination: Path, content: bytes) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            delete=False,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
        temp_path = None
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class ScoreboardAuthorityService:
    def __init__(self, kernel) -> None:
        self._kernel = kernel

    def shadow(
        self,
        *,
        legacy_path: Path,
        classification: list[dict[str, object]],
        projection_version: str,
        source_high_watermark: int,
        acknowledge_manual_source: bool,
        requested_at: datetime,
    ):
        if not acknowledge_manual_source:
            raise ScoreboardAuthorityError(
                "legacy import requires acknowledge_manual_source"
            )
        legacy_bytes = Path(legacy_path).read_bytes()
        digest = hashlib.sha256(legacy_bytes).hexdigest()
        document = self._legacy_document(legacy_bytes)
        legacy_keys = self._legacy_keys(document)
        classified_keys = [
            (str(item.get("group_key", "")), str(item.get("metric_key", "")))
            for item in classification
        ]
        if len(classified_keys) != len(set(classified_keys)) or set(classified_keys) != legacy_keys:
            raise ScoreboardAuthorityError(
                "classification coverage must exactly match every legacy group/metric"
            )
        identity = self._projection_identity()
        if (
            identity.version != projection_version
            or identity.source_high_watermark != source_high_watermark
        ):
            raise ScoreboardAuthorityError(
                "projection version or source high-watermark is stale"
            )
        if high_watermark(self._kernel.engine) != identity.source_high_watermark:
            raise ScoreboardAuthorityError(
                "scoreboard projection is stale against operational actions"
            )

        artifact = self._kernel.artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=legacy_bytes,
                content_type="application/json",
                source_name="legacy-scoreboard",
                source_type="manual-authority-source",
                actor_id="operator:scoreboard-migration",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"scoreboard:legacy:{digest}",
                retrieved_at=requested_at,
            )
        )
        artifact_id = next(
            ref.object_id
            for ref in artifact.result_refs
            if ref.object_type == "source_artifact"
        )
        validated = self._validate_classification(
            document, classification, requested_at=requested_at
        )
        counts = {
            value: sum(item["classification"] == value for item in validated)
            for value in _CLASSIFICATIONS
        }
        review_material = canonical_json(validated).encode("utf-8")
        review_key = hashlib.sha256(review_material).hexdigest()
        return self._kernel.scoreboard_actions.record_shadow_review(
            RecordScoreboardShadowReviewRequest(
                legacy_source_artifact_id=artifact_id,
                legacy_sha256=digest,
                projection_version=projection_version,
                source_high_watermark=source_high_watermark,
                classification=validated,
                matched_count=counts["matched"],
                manual_count=counts["formal_manual"],
                corrected_count=counts["source_correction"],
                unexplained_count=counts["unexplained"],
                status="succeeded",
                actor_id="system:scoreboard-shadow",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=(
                    f"scoreboard:shadow:{digest}:{projection_version}:"
                    f"{source_high_watermark}:{review_key}"
                ),
                requested_at=requested_at,
            )
        )

    def cutover(
        self,
        *,
        legacy_path: Path,
        shadow_review_id: str,
        expected_authority_version: int,
        sop_paths: list[Path],
        approve: bool,
        requested_at: datetime,
    ):
        if not approve:
            raise ScoreboardAuthorityError("cutover requires explicit approve")
        sop = check_sop_authority(sop_paths)
        if not sop.ready:
            raise ScoreboardAuthorityError(
                f"SOP authority statements are incomplete: {sop.missing_by_path}"
            )
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            review = uow.scoreboard.shadow_review(shadow_review_id)
        if review is None:
            raise ScoreboardAuthorityError(
                f"scoreboard shadow review {shadow_review_id} does not exist"
            )
        digest = hashlib.sha256(Path(legacy_path).read_bytes()).hexdigest()
        if digest != review.legacy_sha256:
            raise ScoreboardAuthorityError("legacy scoreboard bytes changed after shadow")
        identity = self._projection_identity()
        if (
            identity.version != review.projection_version
            or identity.source_high_watermark != review.source_high_watermark
        ):
            raise ScoreboardAuthorityError("shadow review projection is no longer current")
        self._assert_shadow_workflow_is_current(review)
        return self._kernel.scoreboard_actions.approve_cutover(
            ApproveScoreboardCutoverRequest(
                shadow_review_id=shadow_review_id,
                legacy_sha256=digest,
                projection_version=identity.version,
                source_high_watermark=identity.source_high_watermark,
                expected_authority_version=expected_authority_version,
                actor_id="operator:scoreboard-cutover",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"scoreboard:cutover:{digest}:{shadow_review_id}",
                requested_at=requested_at,
            )
        )

    def export(self, destination: Path, *, requested_at: datetime) -> ScoreboardExportResult:
        destination = Path(destination)
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            authority = uow.scoreboard.authority()
        if authority.state != "ontology":
            raise ScoreboardAuthorityError("scoreboard authority is not ontology")
        identity = self._projection_identity()
        self._assert_export_projection_is_current(identity)
        if authority.compatibility_export_sha256 is not None and destination.exists():
            existing_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            if existing_hash != authority.compatibility_export_sha256:
                raise ScoreboardExportDriftError(
                    "scoreboard_export_drift: compatibility output was edited"
                )
            if (
                identity.version == authority.projection_version
                and identity.source_high_watermark == authority.source_high_watermark
            ):
                document = json.loads(destination.read_text(encoding="utf-8"))
                return ScoreboardExportResult(
                    path=destination,
                    sha256=existing_hash,
                    action_id=str(document["generation_action_ref"]["object_id"]),
                )
        if authority.compatibility_export_sha256 is not None and not destination.exists():
            raise ScoreboardExportDriftError(
                "scoreboard_export_drift: recorded compatibility output is missing"
            )
        if authority.compatibility_export_sha256 is None and destination.exists():
            existing_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            if existing_hash != authority.legacy_sha256:
                raise ScoreboardExportDriftError(
                    "scoreboard_export_drift: untracked compatibility output already exists"
                )

        if identity.source_high_watermark < authority.source_high_watermark:
            raise ScoreboardAuthorityError("authority projection is stale")
        action_id = f"ACT-{uuid4().hex}"
        content = self._export_bytes(authority, identity, action_id)
        digest = hashlib.sha256(content).hexdigest()
        outcome = self._kernel.scoreboard_actions.record_export(
            RecordScoreboardExportRequest(
                export_sha256=digest,
                projection_version=identity.version,
                source_high_watermark=identity.source_high_watermark,
                expected_authority_version=authority.version,
                actor_id="system:scoreboard-export",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"scoreboard:export:{identity.version}:{identity.source_high_watermark}",
                requested_at=requested_at,
            ),
            action_id=action_id,
        )
        atomic_write(destination, content)
        return ScoreboardExportResult(
            path=destination,
            sha256=digest,
            action_id=outcome.action_id,
        )

    def _actions_after(self, source_high_watermark: int) -> list[dict[str, object]]:
        with self._kernel.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT rowid, action_id, action_type, status, result_refs_json "
                    "FROM actions WHERE rowid > :source_high_watermark ORDER BY rowid"
                ),
                {"source_high_watermark": source_high_watermark},
            ).mappings().all()
        return [
            {
                **dict(row),
                "result_refs": json.loads(str(row["result_refs_json"])),
            }
            for row in rows
        ]

    def _assert_shadow_workflow_is_current(self, review) -> None:
        review_action_seen = False
        for action in self._actions_after(review.source_high_watermark):
            refs = action["result_refs"]
            if (
                action["action_id"] == review.action_id
                and action["action_type"] == "record_scoreboard_shadow_review"
                and action["status"] == "committed"
                and any(
                    ref.get("object_type") == "scoreboard_shadow_review"
                    and ref.get("object_id") == review.scoreboard_shadow_review_id
                    for ref in refs
                )
            ):
                review_action_seen = True
                continue
            if (
                action["action_type"] == "ingest_artifact"
                and action["status"] == "committed"
                and any(
                    ref.get("object_type") == "source_artifact"
                    and ref.get("object_id") == review.legacy_source_artifact_id
                    for ref in refs
                )
            ):
                continue
            raise ScoreboardAuthorityError(
                "scoreboard shadow review is stale against operational actions"
            )
        if not review_action_seen:
            raise ScoreboardAuthorityError(
                "scoreboard shadow review is stale against operational actions"
            )

    def _assert_export_projection_is_current(
        self, identity: ProjectionIdentity
    ) -> None:
        administrative_actions = {
            "ingest_artifact",
            "record_scoreboard_shadow_review",
            "approve_scoreboard_cutover",
            "record_scoreboard_export",
        }
        stale_actions = [
            action
            for action in self._actions_after(identity.source_high_watermark)
            if action["status"] == "committed"
            and action["action_type"] not in administrative_actions
        ]
        if stale_actions:
            raise ScoreboardAuthorityError(
                "scoreboard projection is stale against operational actions"
            )

    def _projection_identity(self) -> ProjectionIdentity:
        path = self._kernel.paths.analytics
        if not path.is_file():
            raise ScoreboardAuthorityError("scoreboard projection is unavailable")
        with connect_analytics_db(path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT projection_version, source_high_watermark, built_at, "
                "cohort_definition_version, metric_version FROM scoreboard_metrics"
            ).fetchall()
        if len(rows) != 1:
            raise ScoreboardAuthorityError("scoreboard projection identity is ambiguous")
        return ProjectionIdentity(
            version=str(rows[0][0]),
            source_high_watermark=int(rows[0][1]),
            built_at=str(rows[0][2]),
            cohort_definition_version=str(rows[0][3]),
            metric_version=str(rows[0][4]),
        )

    def _validate_classification(
        self,
        document: dict[str, object],
        classification: list[dict[str, object]],
        *,
        requested_at: datetime,
    ) -> list[dict[str, object]]:
        projected = self._projected_metrics()
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            observations = {
                (row.group_key, row.metric_key): row
                for row in uow.scoreboard.latest_observations(
                    requested_at.isoformat()
                )
            }
        validated: list[dict[str, object]] = []
        for source in classification:
            item = dict(source)
            group_key = str(item["group_key"])
            metric_key = str(item["metric_key"])
            kind = str(item.get("classification", ""))
            if kind not in _CLASSIFICATIONS:
                raise ScoreboardAuthorityError(
                    f"unknown scoreboard classification {kind}"
                )
            legacy_value = self._legacy_value(document, group_key, metric_key)
            if kind == "formal_manual" and (group_key, metric_key) not in observations:
                raise ScoreboardAuthorityError(
                    f"formal manual observation missing for {group_key}/{metric_key}"
                )
            if kind == "matched":
                target_plane = str(item.get("target_plane", ""))
                target_group = str(item.get("target_group_key", group_key))
                target_metric = str(item.get("target_metric_key", metric_key))
                target = projected.get((target_plane, target_group, target_metric))
                if target is None or target["value"] != legacy_value:
                    raise ScoreboardAuthorityError(
                        f"matched classification differs for {group_key}/{metric_key}"
                    )
            if kind == "source_correction" and (
                not str(item.get("reason", "")).strip()
                or not item.get("evidence_refs")
            ):
                raise ScoreboardAuthorityError(
                    "source_correction requires reason and evidence_refs"
                )
            validated.append(item)
        return sorted(
            validated,
            key=lambda item: (str(item["group_key"]), str(item["metric_key"])),
        )

    def _projected_metrics(self) -> dict[tuple[str, str, str], dict[str, object]]:
        with connect_analytics_db(self._kernel.paths.analytics) as connection:
            columns = [
                row[0]
                for row in connection.execute(
                    "DESCRIBE scoreboard_metrics"
                ).fetchall()
            ]
            records = connection.execute("SELECT * FROM scoreboard_metrics").fetchall()
        decoded = [dict(zip(columns, row, strict=True)) for row in records]
        return {
            (str(row["plane"]), str(row["group_key"]), str(row["metric_key"])): row
            for row in decoded
        }

    def _export_bytes(self, authority, identity: ProjectionIdentity, action_id: str) -> bytes:
        metrics = list(self._projected_metrics().values())
        planes: dict[str, list[dict[str, object]]] = {
            plane: []
            for plane in ("forecast", "money", "intervention", "lifecycle", "manual")
        }
        provenance_keys = {
            "projection_name",
            "projection_version",
            "source_high_watermark",
            "built_at",
            "cohort_definition_version",
            "metric_version",
        }
        for row in metrics:
            plane = str(row["plane"])
            public = {
                key: value
                for key, value in row.items()
                if key not in provenance_keys and key != "plane"
            }
            public["source_refs"] = json.loads(
                str(public.pop("source_refs_json"))
            )
            planes.setdefault(plane, []).append(public)
        for rows in planes.values():
            rows.sort(key=lambda row: (str(row["group_key"]), str(row["metric_key"])))
        document: dict[str, object] = {
            "schema_version": "1",
            "authority": {
                "state": authority.state,
                "source_authority_version": authority.version,
                "legacy_sha256": authority.legacy_sha256,
                "shadow_review_id": authority.shadow_review_id,
                "approved_at": authority.approved_at,
            },
            "projection": {
                "version": identity.version,
                "source_high_watermark": identity.source_high_watermark,
                "built_at": identity.built_at,
                "cohort_definition_version": identity.cohort_definition_version,
                "metric_version": identity.metric_version,
            },
            "planes": planes,
            "generation_action_ref": {
                "object_type": "action",
                "object_id": action_id,
            },
        }
        body_hash = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
        document["content_hash"] = body_hash
        return (canonical_json(document) + "\n").encode("utf-8")

    @staticmethod
    def _legacy_document(content: bytes) -> dict[str, object]:
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ScoreboardAuthorityError("legacy scoreboard is not valid JSON") from error
        if not isinstance(document, dict):
            raise ScoreboardAuthorityError("legacy scoreboard root must be an object")
        return document

    @staticmethod
    def _legacy_keys(document: dict[str, object]) -> set[tuple[str, str]]:
        return {
            (str(group_key), str(metric_key))
            for group_key, group in document.items()
            if isinstance(group, dict)
            for metric_key in group
        }

    @staticmethod
    def _legacy_value(
        document: dict[str, object], group_key: str, metric_key: str
    ) -> object:
        group = document.get(group_key)
        if not isinstance(group, dict) or metric_key not in group:
            raise ScoreboardAuthorityError(
                f"legacy metric {group_key}/{metric_key} does not exist"
            )
        return group[metric_key]

    def recorded_export_action(self, export_sha256: str) -> str | None:
        with self._kernel.engine.connect() as connection:
            rows = connection.execute(
                select(schema.actions.c.action_id, schema.actions.c.payload_json).where(
                    schema.actions.c.action_type == "record_scoreboard_export"
                )
            ).all()
        for action_id, payload_json in rows:
            if json.loads(payload_json).get("export_sha256") == export_sha256:
                return str(action_id)
        return None
