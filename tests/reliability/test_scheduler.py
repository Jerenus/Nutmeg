import plistlib
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_scoreboard
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.reliability.scheduler import inspect_scheduler_authority

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
LABELS = {
    "am": "com.nutmeg.decision.am",
    "close": "com.nutmeg.decision.close",
    "settle": "com.nutmeg.decision.settle",
}
CALENDARS = {
    "am": {"Hour": 8, "Minute": 0},
    "close": {"Hour": 19, "Minute": 0},
    "settle": {"Hour": 8, "Minute": 10},
}


def _kernel(tmp_path: Path, *, ontology_authority: bool = True):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    if ontology_authority:
        with kernel.engine.begin() as connection:
            connection.execute(
                update(schema_scoreboard.scoreboard_authority)
                .where(schema_scoreboard.scoreboard_authority.c.authority_id == "primary")
                .values(state="ontology")
            )
    return kernel


def _plist_document(root: Path, stage: str) -> dict[str, object]:
    label = LABELS[stage]
    return {
        "Label": label,
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            (
                f"cd {root} && uv run python scripts/openclaw/"
                f"nutmeg_scheduler_ops.py run-strict --stage {stage} "
                "--run-date 2026-08-24"
            ),
        ],
        "StartCalendarInterval": CALENDARS[stage],
        "StandardOutPath": str(root / ".nutmeg-data" / "logs" / f"{stage}.out.log"),
        "StandardErrorPath": str(root / ".nutmeg-data" / "logs" / f"{stage}.err.log"),
        "WorkingDirectory": str(root),
    }


def _write_plists(root: Path, documents=None) -> list[Path]:
    documents = documents or {
        stage: _plist_document(root, stage) for stage in LABELS
    }
    output = root / "plist-fixtures"
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, (stage, document) in enumerate(documents.items()):
        path = output / f"{index}-{stage}.plist"
        with path.open("wb") as handle:
            plistlib.dump(document, handle)
        paths.append(path)
    return paths


def _runtime(root: Path, *, loaded=None, ontology_v2=True) -> Path:
    import json

    path = root / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "scheduler-runtime-v1",
                "candidate_commit": "abc123",
                "loaded_labels": loaded if loaded is not None else list(LABELS.values()),
                "effective_environment": {
                    "NUTMEG_ONTOLOGY_V2": "1" if ontology_v2 else "0",
                    "TELEGRAM_BOT_TOKEN": "top-secret-must-not-leak",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _sop(root: Path) -> list[Path]:
    target = root / "sop"
    shutil.copytree(Path("tests/fixtures/m5/sop"), target)
    return sorted(target.iterdir())


def test_scheduler_review_passes_exact_read_only_authority_contract(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    kernel = _kernel(tmp_path)
    report = inspect_scheduler_authority(
        kernel=kernel,
        plist_paths=_write_plists(project_root),
        runtime_report_path=_runtime(project_root),
        sop_paths=_sop(tmp_path),
        expected_project_root=project_root,
        requested_at=NOW,
    )

    assert report.passed is True
    assert report.candidate_commit == "abc123"
    assert report.ontology_v2 is True
    assert report.scoreboard_authority == "ontology"
    assert tuple(report.stages) == ("am", "close", "settle")
    assert all(stage.configured and stage.loaded for stage in report.stages.values())
    evidence = report.to_evidence_report()
    assert evidence["checks"] and all(evidence["checks"].values())
    rendered = canonical_json(report.to_dict())
    assert "top-secret-must-not-leak" not in rendered
    assert "TELEGRAM_BOT_TOKEN" not in rendered


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing_stage", "missing_stage:settle"),
        ("duplicate_stage", "duplicate_stage:am"),
        ("wrong_root", "wrong_working_directory:close"),
        ("wrong_argument", "wrong_stage_argument:settle"),
        ("missing_calendar", "missing_calendar:am"),
        ("missing_log", "invalid_log_path:close"),
        ("unloaded", "stage_unloaded:settle"),
        ("ontology_false", "ontology_v2_disabled"),
        ("legacy_authority", "scoreboard_authority_not_ontology"),
        ("incomplete_sop", "sop_authority_incomplete"),
    ],
)
def test_scheduler_review_blocks_each_authority_drift(
    tmp_path: Path, case: str, expected_code: str
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    kernel = _kernel(tmp_path, ontology_authority=case != "legacy_authority")
    documents = {stage: _plist_document(project_root, stage) for stage in LABELS}
    if case == "missing_stage":
        del documents["settle"]
    elif case == "duplicate_stage":
        documents["am-copy"] = deepcopy(documents["am"])
    elif case == "wrong_root":
        documents["close"]["WorkingDirectory"] = str(tmp_path / "wrong")
    elif case == "wrong_argument":
        documents["settle"]["ProgramArguments"][-1] = "run-strict --stage am"
    elif case == "missing_calendar":
        del documents["am"]["StartCalendarInterval"]
    elif case == "missing_log":
        del documents["close"]["StandardErrorPath"]
    runtime = _runtime(
        project_root,
        loaded=(
            [LABELS["am"], LABELS["close"]]
            if case == "unloaded"
            else list(LABELS.values())
        ),
        ontology_v2=case != "ontology_false",
    )
    sop_paths = _sop(tmp_path)
    if case == "incomplete_sop":
        sop_paths[0].write_text("incomplete\n", encoding="utf-8")

    report = inspect_scheduler_authority(
        kernel=kernel,
        plist_paths=_write_plists(project_root, documents),
        runtime_report_path=runtime,
        sop_paths=sop_paths,
        expected_project_root=project_root,
        requested_at=NOW,
    )

    assert report.passed is False
    assert expected_code in report.issues
