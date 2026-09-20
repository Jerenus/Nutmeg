"""JCZQ ontology authority queries and replay-gated cutover Action."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.product.jczq_replay import _derive_replay_metrics

_ZERO_DELTA = {
    "objects": 0,
    "money_entries": 0,
    "dispatches": 0,
    "prospective_observations": 0,
}
_REPLAY_GATE_DAY = "2026-09-19"
_REQUIRED_BANDS = ["10x", "20x", "50x", "100x"]


@dataclass(frozen=True, slots=True)
class JczqCutoverReadiness:
    day: str
    report_sha256: str
    schema_version: int
    accepted: bool
    authority: str

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day,
            "report_sha256": self.report_sha256,
            "schema_version": self.schema_version,
            "accepted": self.accepted,
            "authority": self.authority,
        }


def _report_hash(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "report_sha256"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class JczqCutoverGate:
    def __init__(self, action_service, *, schema_version: int) -> None:
        self._action_service = action_service
        self._schema_version = schema_version

    def authority(self) -> str:
        with self._action_service.unit_of_work() as uow:
            action = uow.actions.latest_committed("approve_jczq_ontology_cutover")
        return "ontology_v2_required" if action is not None else "legacy_read_only"

    def check(self, day: str, replay_report: str | Path) -> JczqCutoverReadiness:
        document = json.loads(Path(replay_report).expanduser().read_text("utf-8"))
        if not isinstance(document, dict) or document.get("accepted") is not True:
            raise ValueError("accepted replay is required")
        if document.get("schema_version") != self._schema_version:
            raise ValueError("replay schema version does not match the current ontology")
        if document.get("production_delta") != _ZERO_DELTA:
            raise ValueError("replay report contains production side effects")
        expected = _report_hash(document)
        if document.get("report_sha256") != expected:
            raise ValueError("replay report hash is invalid")
        if document.get("day") != _REPLAY_GATE_DAY:
            raise ValueError("replay day is not the approved gate day")
        self._verify_isolated_replay(document, expected)
        if document.get("failures") != []:
            raise ValueError("replay report is incomplete")
        return JczqCutoverReadiness(
            day=day,
            report_sha256=expected,
            schema_version=self._schema_version,
            accepted=True,
            authority=self.authority(),
        )

    def _verify_isolated_replay(
        self, document: dict[str, object], expected_hash: str
    ) -> None:
        database_value = document.get("isolated_database_identity")
        replay_run_id = document.get("replay_run_id")
        if not isinstance(database_value, str) or not isinstance(replay_run_id, str):
            raise ValueError("replay report is missing isolated database identity")
        database = Path(database_value).expanduser().resolve()
        if not database.is_file():
            raise ValueError("isolated replay database is missing")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            run = connection.execute(
                "SELECT * FROM historical_replay_runs WHERE replay_run_id = ?",
                (replay_run_id,),
            ).fetchone()
            if run is None or run["status"] != "accepted":
                raise ValueError("isolated replay run is not accepted")
            if (
                run["business_date"] != document.get("day")
                or run["source_manifest_hash"] != document.get("source_manifest_hash")
                or run["isolated_database_identity"] != str(database)
                or run["schema_version"] != document.get("schema_version")
                or run["report_sha256"] != expected_hash
                or json.loads(run["failure_codes_json"]) != []
            ):
                raise ValueError("replay report disagrees with isolated replay run")
            research_rows = tuple(
                connection.execute(
                    "SELECT status, COUNT(*) AS count "
                    "FROM operator_jczq_board_research_state_revisions "
                    "WHERE business_date = ? GROUP BY status",
                    (document["day"],),
                ).fetchall()
            )
            research_counts = {
                str(row["status"]): int(row["count"]) for row in research_rows
            }
            board_count = sum(research_counts.values())
            before = json.loads(run["production_before_json"])
            after = json.loads(run["production_after_json"])
        finally:
            connection.close()

        isolated_root = database.parent.parent
        manifest_path = isolated_root / f"replay-input-manifest-{document['day']}.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("frozen replay input manifest is missing or invalid") from error
        if not isinstance(manifest, dict):
            raise ValueError("frozen replay input manifest is invalid")
        entries = manifest.get("entries")
        quarantined = manifest.get("quarantined")
        if not isinstance(entries, list) or not isinstance(quarantined, list):
            raise ValueError("frozen replay input manifest is invalid")
        manifest_material = {"entries": entries, "quarantined": quarantined}
        manifest_hash = hashlib.sha256(
            canonical_json(manifest_material).encode("utf-8")
        ).hexdigest()
        if (
            manifest.get("manifest_hash") != manifest_hash
            or manifest_hash != document.get("source_manifest_hash")
        ):
            raise ValueError("frozen replay input manifest hash is invalid")
        input_root = isolated_root / "jczq" / "daily" / str(document["day"])
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("relative_path"), str
            ):
                raise ValueError("frozen replay input manifest entry is invalid")
            path = input_root / entry["relative_path"]
            try:
                data = path.read_bytes()
            except OSError as error:
                raise ValueError("frozen replay input is missing") from error
            if (
                len(data) != entry.get("byte_size")
                or hashlib.sha256(data).hexdigest() != entry.get("sha256")
            ):
                raise ValueError("frozen replay input hash is invalid")

        metrics = _derive_replay_metrics(database, replay_run_id)
        bands = sorted(
            {
                str(outcome["odds_band"])
                for outcome in metrics["structured_band_outcomes"]
            },
            key=_REQUIRED_BANDS.index,
        )
        result_count = int(metrics["authoritative_result_count"])
        derived = {
            "run_status": "accepted",
            "board_count": board_count,
            "research_terminal_count": board_count,
            "research_status_counts": research_counts,
            "missing_lineage": [],
            "odds_band_outcomes": bands,
            "replay_action_counts": metrics["replay_action_counts"],
            "adjudication_branch_counts": metrics["adjudication_branch_counts"],
            "committed_forecast_count": metrics["committed_forecast_count"],
            "evidence_lineage_count": metrics["evidence_lineage_count"],
            "judgment_prescription_revision_id": metrics[
                "judgment_prescription_revision_id"
            ],
            "candidate_set_revision_ids": list(metrics["candidate_set_revision_ids"]),
            "structured_band_outcomes": list(metrics["structured_band_outcomes"]),
            "audit_complete": metrics["audit_complete"],
            "terminal_kind": "no_ticket" if metrics["no_ticket_revision_id"] else "missing",
            "no_ticket_revision_id": metrics["no_ticket_revision_id"],
            "authoritative_result_count": result_count,
            "replay_prediction_count": metrics["replay_prediction_count"],
            "replay_score_count": metrics["replay_score_count"],
            "rsi_statuses": {
                experiment: "replay_excluded" if result_count else "replay_gap"
                for experiment in ("R0", "F5", "F9")
            },
            "quarantined_gaps": [
                f"{item['relative_path']}:{item['reason']}"
                for item in quarantined
                if isinstance(item, dict)
                and isinstance(item.get("relative_path"), str)
                and isinstance(item.get("reason"), str)
            ],
            "production_before_fingerprint": before["tree_fingerprint"],
            "production_after_fingerprint": after["tree_fingerprint"],
            "protected_replay_counts": metrics["protected_replay_counts"],
        }
        for field, value in derived.items():
            if document.get(field) != value:
                raise ValueError(f"replay report disagrees with isolated state:{field}")
        if (
            board_count == 0
            or metrics["committed_forecast_count"] != board_count
            or metrics["evidence_lineage_count"] != board_count
            or bands != _REQUIRED_BANDS
            or len(metrics["structured_band_outcomes"]) != 8
            or result_count != board_count
            or metrics["replay_prediction_count"] != board_count
            or metrics["replay_score_count"] != board_count
            or any(metrics["protected_replay_counts"].values())
            or before.get("tree_fingerprint") != after.get("tree_fingerprint")
            or before.get("protected_counts") != after.get("protected_counts")
        ):
            raise ValueError("replay report is incomplete")

    def approve(
        self,
        day: str,
        replay_report: str | Path,
        *,
        actor_id: str,
        requested_at: datetime | None = None,
    ) -> JczqCutoverReadiness:
        readiness = self.check(day, replay_report)
        command = ActionCommand.create(
            action_type="approve_jczq_ontology_cutover",
            actor_id=actor_id,
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"jczq-cutover:{day}:{readiness.report_sha256}",
            payload={
                "day": day,
                "report_sha256": readiness.report_sha256,
                "schema_version": readiness.schema_version,
                "production_delta": _ZERO_DELTA,
            },
            requested_at=requested_at or datetime.now(UTC),
        )

        outcome = self._action_service.execute(
            command,
            lambda _uow, _command: (ObjectRef("jczq_authority", "primary"),),
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("JCZQ ontology cutover Action did not commit")
        return JczqCutoverReadiness(
            day=day,
            report_sha256=readiness.report_sha256,
            schema_version=readiness.schema_version,
            accepted=True,
            authority="ontology_v2_required",
        )


__all__ = ["JczqCutoverGate", "JczqCutoverReadiness"]
