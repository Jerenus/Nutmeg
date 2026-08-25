"""Read-only launchd, runtime, SOP, and authority inspection."""
from __future__ import annotations

import json
import plistlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.scoreboard.authority import check_sop_authority

_STAGES = {
    "am": {
        "label": "com.nutmeg.decision.am",
        "calendar": {"Hour": 8, "Minute": 0},
    },
    "close": {
        "label": "com.nutmeg.decision.close",
        "calendar": {"Hour": 19, "Minute": 0},
    },
    "settle": {
        "label": "com.nutmeg.decision.settle",
        "calendar": {"Hour": 8, "Minute": 10},
    },
}
_LABEL_TO_STAGE = {
    str(spec["label"]): stage for stage, spec in _STAGES.items()
}


@dataclass(frozen=True, slots=True)
class SchedulerStageReport:
    stage: str
    label: str
    plist_path: str | None
    configured: bool
    loaded: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "label": self.label,
            "plist_path": self.plist_path,
            "configured": self.configured,
            "loaded": self.loaded,
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class SchedulerAuthorityReport:
    passed: bool
    candidate_commit: str
    requested_at: str
    expected_project_root: str
    ontology_v2: bool
    scoreboard_authority: str
    sop_ready: bool
    stages: dict[str, SchedulerStageReport]
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "candidate_commit": self.candidate_commit,
            "requested_at": self.requested_at,
            "expected_project_root": self.expected_project_root,
            "ontology_v2": self.ontology_v2,
            "scoreboard_authority": self.scoreboard_authority,
            "sop_ready": self.sop_ready,
            "stages": [self.stages[stage].to_dict() for stage in self.stages],
            "issues": list(self.issues),
        }

    def to_evidence_report(self) -> dict[str, object]:
        checks: dict[str, bool] = {}
        for stage, report in self.stages.items():
            checks[f"{stage}_configured"] = report.configured
            checks[f"{stage}_loaded"] = report.loaded
        checks.update(
            {
                "ontology_v2": self.ontology_v2,
                "scoreboard_authority": self.scoreboard_authority == "ontology",
                "sop_authority": self.sop_ready,
            }
        )
        return {
            "candidate_commit": self.candidate_commit,
            "policy_version": "release-v1",
            "checks": checks,
            "schema_version": "scheduler-v1",
            "summary": self.to_dict(),
        }


def _runtime(path: Path) -> tuple[str, set[str], bool]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("runtime report must be readable JSON") from error
    if not isinstance(document, dict):
        raise ValueError("runtime report must be an object")
    if document.get("schema_version") != "scheduler-runtime-v1":
        raise ValueError("runtime report schema_version must be scheduler-runtime-v1")
    candidate = document.get("candidate_commit")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("runtime report candidate_commit is required")
    labels = document.get("loaded_labels")
    if not isinstance(labels, list) or any(not isinstance(item, str) for item in labels):
        raise ValueError("runtime report loaded_labels must be an array of strings")
    environment = document.get("effective_environment")
    if not isinstance(environment, dict):
        raise ValueError("runtime report effective_environment must be an object")
    raw_flag = environment.get("NUTMEG_ONTOLOGY_V2")
    if isinstance(raw_flag, bool):
        ontology_v2 = raw_flag
    elif isinstance(raw_flag, str):
        ontology_v2 = raw_flag.strip().casefold() in {"1", "true", "yes", "on"}
    else:
        ontology_v2 = False
    return candidate, set(labels), ontology_v2


def _load_plists(paths: list[Path]) -> tuple[dict[str, list[tuple[Path, dict]]], list[str]]:
    by_stage: dict[str, list[tuple[Path, dict]]] = {
        stage: [] for stage in _STAGES
    }
    issues: list[str] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        try:
            with path.open("rb") as handle:
                document = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            issues.append("invalid_plist")
            continue
        if not isinstance(document, dict):
            issues.append("invalid_plist")
            continue
        label = document.get("Label")
        stage = _LABEL_TO_STAGE.get(str(label))
        if stage is None:
            issues.append("unknown_stage_label")
            continue
        by_stage[stage].append((path, document))
    return by_stage, issues


def _stage_report(
    stage: str,
    entries: list[tuple[Path, dict]],
    *,
    loaded_labels: set[str],
    project_root: Path,
) -> SchedulerStageReport:
    label = str(_STAGES[stage]["label"])
    issues: list[str] = []
    if not entries:
        issues.append(f"missing_stage:{stage}")
        return SchedulerStageReport(stage, label, None, False, False, tuple(issues))
    if len(entries) > 1:
        issues.append(f"duplicate_stage:{stage}")
    path, document = entries[0]
    working_directory = document.get("WorkingDirectory")
    if not isinstance(working_directory, str) or Path(working_directory).resolve() != project_root:
        issues.append(f"wrong_working_directory:{stage}")
    arguments = document.get("ProgramArguments")
    command = ""
    if isinstance(arguments, list) and all(isinstance(item, str) for item in arguments):
        command = " ".join(arguments)
    stage_pattern = rf"(?:^|\s)--stage\s+{re.escape(stage)}(?:\s|$)"
    if (
        "nutmeg_scheduler_ops.py" not in command
        or "run-strict" not in command
        or re.search(stage_pattern, command) is None
    ):
        issues.append(f"wrong_stage_argument:{stage}")
    if document.get("StartCalendarInterval") != _STAGES[stage]["calendar"]:
        issues.append(f"missing_calendar:{stage}")
    expected_log_root = project_root / ".nutmeg-data" / "logs"
    for key in ("StandardOutPath", "StandardErrorPath"):
        raw_log = document.get(key)
        if (
            not isinstance(raw_log, str)
            or not Path(raw_log).is_absolute()
            or Path(raw_log).resolve().parent != expected_log_root
        ):
            issues.append(f"invalid_log_path:{stage}")
            break
    loaded = label in loaded_labels
    if not loaded:
        issues.append(f"stage_unloaded:{stage}")
    configured = not any(
        issue != f"stage_unloaded:{stage}" for issue in issues
    )
    return SchedulerStageReport(
        stage=stage,
        label=label,
        plist_path=str(path),
        configured=configured,
        loaded=loaded,
        issues=tuple(issues),
    )


def inspect_scheduler_authority(
    *,
    kernel,
    plist_paths: list[Path],
    runtime_report_path: Path,
    sop_paths: list[Path],
    expected_project_root: Path,
    requested_at: datetime,
) -> SchedulerAuthorityReport:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    project_root = Path(expected_project_root).expanduser().resolve()
    candidate, loaded_labels, ontology_v2 = _runtime(
        Path(runtime_report_path).expanduser().resolve()
    )
    entries, issues = _load_plists(plist_paths)
    stages = {
        stage: _stage_report(
            stage,
            entries[stage],
            loaded_labels=loaded_labels,
            project_root=project_root,
        )
        for stage in ("am", "close", "settle")
    }
    issues.extend(issue for report in stages.values() for issue in report.issues)
    if not ontology_v2:
        issues.append("ontology_v2_disabled")
    with OntologyUnitOfWork(kernel.engine) as uow:
        authority = uow.scoreboard.authority().state
    if authority != "ontology":
        issues.append("scoreboard_authority_not_ontology")
    sop = check_sop_authority([Path(path).expanduser().resolve() for path in sop_paths])
    if not sop.ready:
        issues.append("sop_authority_incomplete")
    unique_issues = tuple(dict.fromkeys(issues))
    return SchedulerAuthorityReport(
        passed=not unique_issues,
        candidate_commit=candidate,
        requested_at=requested_at.astimezone(UTC).isoformat(),
        expected_project_root=str(project_root),
        ontology_v2=ontology_v2,
        scoreboard_authority=authority,
        sop_ready=sop.ready,
        stages=stages,
        issues=unique_issues,
    )
