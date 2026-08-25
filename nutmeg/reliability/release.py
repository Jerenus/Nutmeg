"""Deterministic release-v1 gate evaluation over immutable evidence."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.reliability.models import ReliabilityEvidenceRow
from nutmeg.ontology.repository.reliability import ReliabilityRepository
from nutmeg.reliability.contracts import (
    RELEASE_POLICY_VERSION,
    validate_evidence_report,
    validate_soak_report,
)

_GATE_REQUIREMENTS = {
    "G1": ("scheduler_authority",),
    "G2": ("deterministic_suite", "migration_replay"),
    "G3": ("fault_matrix",),
    "G4": ("ai_safety",),
    "G5": ("browser_e2e", "performance"),
    "G6": ("backup_restore", "observability"),
}
_GATE_NAMES = {
    "G1": "single-track authority",
    "G2": "deterministic integrity",
    "G3": "fault tolerance",
    "G4": "AI safety",
    "G5": "product experience",
    "G6": "operations",
}


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    gate_id: str
    name: str
    passed: bool
    code: str
    detail: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "passed": self.passed,
            "code": self.code,
            "detail": self.detail,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class SoakCoverage:
    workflow: str
    dates: tuple[str, ...]
    distinct_days: int
    first_date: str | None
    last_date: str | None
    inclusive_span_days: int

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow": self.workflow,
            "dates": list(self.dates),
            "distinct_days": self.distinct_days,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "inclusive_span_days": self.inclusive_span_days,
        }


@dataclass(frozen=True, slots=True)
class ReleaseEvaluation:
    release_version: str
    candidate_commit: str
    policy_version: str
    evaluated_at: str
    ready: bool
    gates: dict[str, ReleaseGate]
    selected_evidence: tuple[ReliabilityEvidenceRow, ...]
    soak_coverage: dict[str, SoakCoverage]
    evidence_snapshot_sha256: str
    approval_status: str


def _aware_from_iso(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _blocked(
    gate_id: str,
    code: str,
    detail: str,
    rows: list[ReliabilityEvidenceRow],
) -> ReleaseGate:
    return ReleaseGate(
        gate_id=gate_id,
        name=_GATE_NAMES[gate_id],
        passed=False,
        code=code,
        detail=detail,
        evidence_ids=tuple(sorted(row.reliability_evidence_id for row in rows)),
    )


def _passed(gate_id: str, rows: list[ReliabilityEvidenceRow]) -> ReleaseGate:
    return ReleaseGate(
        gate_id=gate_id,
        name=_GATE_NAMES[gate_id],
        passed=True,
        code="passed",
        detail="all required evidence passed",
        evidence_ids=tuple(sorted(row.reliability_evidence_id for row in rows)),
    )


class ReleaseEvaluator:
    def __init__(self, repository: ReliabilityRepository) -> None:
        self._repository = repository

    def evaluate(
        self,
        release_version: str,
        *,
        candidate_commit: str,
        evaluated_at: datetime,
    ) -> ReleaseEvaluation:
        if not release_version.strip():
            raise ValueError("release_version is required")
        if not candidate_commit.strip():
            raise ValueError("candidate_commit is required")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")

        selected: dict[str, ReliabilityEvidenceRow] = {}
        gates: dict[str, ReleaseGate] = {}
        for gate_id in ("G1", "G2", "G3", "G4", "G5"):
            gate = self._evaluate_required(
                gate_id,
                candidate_commit=candidate_commit,
                evaluated_at=evaluated_at,
                selected=selected,
            )
            gates[gate_id] = gate
        gates["G6"], soak_coverage = self._evaluate_operations(
            candidate_commit=candidate_commit,
            evaluated_at=evaluated_at,
            selected=selected,
        )

        selected_rows = tuple(
            selected[key]
            for key in sorted(
                selected,
                key=lambda row_id: (
                    row_id,
                    selected[row_id].content_hash,
                ),
            )
        )
        snapshot_material = {
            "release_version": release_version,
            "candidate_commit": candidate_commit,
            "policy_version": RELEASE_POLICY_VERSION,
            "gates": [gates[gate_id].to_dict() for gate_id in gates],
            "evidence": [
                [row.reliability_evidence_id, row.content_hash]
                for row in selected_rows
            ],
        }
        snapshot = hashlib.sha256(
            canonical_json(snapshot_material).encode("utf-8")
        ).hexdigest()
        approval = self._repository.approval_for_release(release_version)
        approval_status = "none"
        if approval is not None:
            approval_status = (
                "current"
                if approval.evidence_snapshot_sha256 == snapshot
                else "superseded"
            )
        return ReleaseEvaluation(
            release_version=release_version,
            candidate_commit=candidate_commit,
            policy_version=RELEASE_POLICY_VERSION,
            evaluated_at=evaluated_at.isoformat(),
            ready=all(gate.passed for gate in gates.values()),
            gates=gates,
            selected_evidence=selected_rows,
            soak_coverage=soak_coverage,
            evidence_snapshot_sha256=snapshot,
            approval_status=approval_status,
        )

    def _evaluate_required(
        self,
        gate_id: str,
        *,
        candidate_commit: str,
        evaluated_at: datetime,
        selected: dict[str, ReliabilityEvidenceRow],
    ) -> ReleaseGate:
        rows: list[ReliabilityEvidenceRow] = []
        missing: list[str] = []
        for kind in _GATE_REQUIREMENTS[gate_id]:
            candidates = self._repository.list_evidence(kind=kind)
            if not candidates:
                missing.append(kind)
                continue
            row = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.report.get("candidate_commit")
                    == candidate_commit
                ),
                candidates[0],
            )
            rows.append(row)
            selected[row.reliability_evidence_id] = row
        if missing:
            return _blocked(
                gate_id,
                "missing_evidence",
                f"missing evidence: {', '.join(missing)}",
                rows,
            )
        for row in rows:
            if row.report.get("candidate_commit") != candidate_commit:
                return _blocked(
                    gate_id,
                    "candidate_mismatch",
                    f"{row.evidence_kind} belongs to another candidate",
                    rows,
                )
            if row.report.get("policy_version") != RELEASE_POLICY_VERSION:
                return _blocked(
                    gate_id,
                    "policy_mismatch",
                    f"{row.evidence_kind} uses another policy",
                    rows,
                )
            try:
                observed_to = _aware_from_iso(row.observed_to, "observed_to")
                recorded_at = _aware_from_iso(row.recorded_at, "recorded_at")
            except ValueError as error:
                return _blocked(gate_id, "invalid_evidence", str(error), rows)
            if observed_to > evaluated_at or recorded_at > evaluated_at:
                return _blocked(
                    gate_id,
                    "future_evidence",
                    f"{row.evidence_kind} is later than evaluation time",
                    rows,
                )
            try:
                result = validate_evidence_report(row.evidence_kind, row.report)
            except ValueError as error:
                return _blocked(gate_id, "invalid_evidence", str(error), rows)
            if row.status != "passed" or not result.passed:
                return _blocked(
                    gate_id,
                    "evidence_failed",
                    f"{row.evidence_kind} did not pass",
                    rows,
                )
        return _passed(gate_id, rows)

    def _evaluate_operations(
        self,
        *,
        candidate_commit: str,
        evaluated_at: datetime,
        selected: dict[str, ReliabilityEvidenceRow],
    ) -> tuple[ReleaseGate, dict[str, SoakCoverage]]:
        dependencies = self._evaluate_required(
            "G6",
            candidate_commit=candidate_commit,
            evaluated_at=evaluated_at,
            selected=selected,
        )
        empty_coverage = {
            workflow: SoakCoverage(workflow, (), 0, None, None, 0)
            for workflow in ("jczq", "zucai")
        }
        if not dependencies.passed:
            return dependencies, empty_coverage

        dependency_rows = [
            selected[evidence_id] for evidence_id in dependencies.evidence_ids
        ]
        latest: dict[tuple[str, str], ReliabilityEvidenceRow] = {}
        for row in self._repository.list_evidence(kind="soak_run"):
            if row.workflow not in {"jczq", "zucai"} or row.business_date is None:
                selected[row.reliability_evidence_id] = row
                return (
                    _blocked(
                        "G6",
                        "invalid_evidence",
                        "soak row requires workflow and business_date",
                        [*dependency_rows, row],
                    ),
                    empty_coverage,
                )
            try:
                parsed_date = datetime.strptime(row.business_date, "%Y-%m-%d")
            except ValueError:
                selected[row.reliability_evidence_id] = row
                return (
                    _blocked(
                        "G6",
                        "invalid_evidence",
                        "business_date must use YYYY-MM-DD",
                        [*dependency_rows, row],
                    ),
                    empty_coverage,
                )
            if parsed_date.strftime("%Y-%m-%d") != row.business_date:
                selected[row.reliability_evidence_id] = row
                return (
                    _blocked(
                        "G6",
                        "invalid_evidence",
                        "business_date must use YYYY-MM-DD",
                        [*dependency_rows, row],
                    ),
                    empty_coverage,
                )
            latest.setdefault((row.workflow, row.business_date), row)

        soak_rows = list(latest.values())
        for row in soak_rows:
            selected[row.reliability_evidence_id] = row
        gate_rows = [*dependency_rows, *soak_rows]
        coverage = self._coverage(soak_rows)
        for row in soak_rows:
            try:
                business_date = datetime.strptime(row.business_date or "", "%Y-%m-%d").date()
                observed_to = _aware_from_iso(row.observed_to, "observed_to")
                recorded_at = _aware_from_iso(row.recorded_at, "recorded_at")
                result = validate_soak_report(row.report)
            except ValueError as error:
                return _blocked("G6", "invalid_evidence", str(error), gate_rows), coverage
            if (
                business_date > evaluated_at.date()
                or observed_to > evaluated_at
                or recorded_at > evaluated_at
            ):
                return (
                    _blocked(
                        "G6",
                        "soak_future_date",
                        f"{row.workflow}/{row.business_date} is in the future",
                        gate_rows,
                    ),
                    coverage,
                )
            if "synthetic_evidence" in result.failures:
                return _blocked("G6", "soak_synthetic", "synthetic soak row", gate_rows), coverage
            if "dispatch_enabled" in result.failures:
                return (
                    _blocked(
                        "G6",
                        "soak_dispatch",
                        "dispatch-enabled soak row",
                        gate_rows,
                    ),
                    coverage,
                )
            if any(failure.endswith("_divergence") for failure in result.failures):
                return _blocked("G6", "soak_divergence", "soak divergence", gate_rows), coverage
            if row.status != "passed" or not result.passed:
                return _blocked("G6", "evidence_failed", "soak row failed", gate_rows), coverage

        if any(
            item.distinct_days < 14 or item.inclusive_span_days < 14
            for item in coverage.values()
        ):
            return (
                _blocked(
                    "G6",
                    "soak_days_insufficient",
                    "both workflows require 14 distinct days and a 14-day span",
                    gate_rows,
                ),
                coverage,
            )
        return _passed("G6", gate_rows), coverage

    @staticmethod
    def _coverage(
        rows: list[ReliabilityEvidenceRow],
    ) -> dict[str, SoakCoverage]:
        result: dict[str, SoakCoverage] = {}
        for workflow in ("jczq", "zucai"):
            dates = tuple(
                sorted(
                    {
                        row.business_date
                        for row in rows
                        if row.workflow == workflow and row.business_date is not None
                    }
                )
            )
            if dates:
                first = datetime.strptime(dates[0], "%Y-%m-%d").date()
                last = datetime.strptime(dates[-1], "%Y-%m-%d").date()
                span = (last - first).days + 1
            else:
                first = last = None
                span = 0
            result[workflow] = SoakCoverage(
                workflow=workflow,
                dates=dates,
                distinct_days=len(dates),
                first_date=None if first is None else first.isoformat(),
                last_date=None if last is None else last.isoformat(),
                inclusive_span_days=span,
            )
        return result
