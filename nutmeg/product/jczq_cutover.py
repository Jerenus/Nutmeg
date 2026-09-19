"""JCZQ ontology authority queries and replay-gated cutover Action."""

from __future__ import annotations

import hashlib
import json
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
        if (
            document.get("board_count") != 30
            or document.get("research_terminal_count") != 30
            or document.get("missing_lineage") != []
            or document.get("odds_band_outcomes") != _REQUIRED_BANDS
            or document.get("terminal_kind") not in {"selected", "no_ticket"}
            or document.get("failures") != []
        ):
            raise ValueError("replay report is incomplete")
        return JczqCutoverReadiness(
            day=day,
            report_sha256=expected,
            schema_version=self._schema_version,
            accepted=True,
            authority=self.authority(),
        )

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
