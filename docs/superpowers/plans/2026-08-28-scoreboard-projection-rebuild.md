# Scoreboard Projection Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add an explicit build-only `nutmeg scoreboard rebuild-projection` command that refreshes the M5 DuckDB projection after operational Actions and before a shadow review.

**Architecture:** The command is a thin adapter over the existing guarded scoreboard kernel and `CalibrateService.build`. It validates explicit aware timestamps, builds at the current SQLite Action high-watermark, emits the frozen `sb-v1` identity, and performs no typed Action or authority mutation.

**Tech Stack:** Python 3.12, Typer, SQLAlchemy/SQLite, DuckDB, pytest, existing Nutmeg ontology kernel.

---

## File structure

- Create `tests/product/test_scoreboard_projection_cli.py`: isolated CLI contract and stale-to-fresh shadow chain.
- Modify `nutmeg/interfaces/cli/scoreboard.py`: build-only command, canonical output, and failure mapping.
- Modify `docs/nutmeg-intelligence-os-m5-operations.md`: replace the direct service workaround with the public CLI sequence.

No repository, schema, Action, projector, authority, or production data file changes are required.

### Task 1: Specify the build-only CLI and stale-to-fresh chain

**Files:**
- Create: `tests/product/test_scoreboard_projection_cli.py`

- [x] **Step 1: Write the failing CLI tests**

Create the test module with isolated helpers and two tests:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import ActorRole, ObjectRef, canonical_json
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardObservationRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _invoke(*args: str):
    return CliRunner().invoke(app, ["scoreboard", *args])


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert result.stdout.strip() == canonical_json(payload)
    return payload


def _observe(kernel, *, metric_key: str, key: str) -> None:
    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="chains",
            metric_key=metric_key,
            tally="1/1",
            detail=f"formal manual observation {metric_key}",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("adjudication", f"adj-{metric_key}")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT,
        )
    )


def _action_watermark(kernel) -> int:
    with OntologyUnitOfWork(kernel.engine) as uow:
        value = uow.connection.exec_driver_sql(
            "SELECT max(rowid) FROM actions"
        ).scalar_one()
    return int(value or 0)


def _shadow_args(
    data_dir: Path,
    legacy: Path,
    classification: Path,
    watermark: int,
) -> list[str]:
    return [
        "shadow",
        "--data-dir",
        str(data_dir),
        "--legacy-file",
        str(legacy),
        "--classification-file",
        str(classification),
        "--projection-version",
        "sb-v1",
        "--source-high-watermark",
        str(watermark),
        "--requested-at",
        AT.isoformat(),
        "--acknowledge-manual-source",
    ]


def test_rebuild_projection_refreshes_stale_shadow_without_action_write(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    _observe(kernel, metric_key="main", key="rebuild:main")

    first_before = _action_watermark(kernel)
    first = _json(
        _invoke(
            "rebuild-projection",
            "--data-dir",
            str(data_dir),
            "--as-of",
            AT.isoformat(),
            "--built-at",
            "2026-08-24T10:05:00+00:00",
        )
    )
    assert first["status"] == "succeeded"
    assert first["projection_version"] == "sb-v1"
    assert first["source_high_watermark"] == first_before
    assert _action_watermark(kernel) == first_before

    legacy = tmp_path / "scoreboard.json"
    legacy.write_text(
        '{"updated_at":"2026-08-24T09:00:00Z","chains":{"main":1}}\n',
        encoding="utf-8",
    )
    classification = tmp_path / "classification.json"
    classification.write_text(
        canonical_json(
            [
                {
                    "group_key": "chains",
                    "metric_key": "main",
                    "classification": "formal_manual",
                    "target_ref": "scoreboard_observation:chains:main",
                }
            ]
        ),
        encoding="utf-8",
    )

    _observe(kernel, metric_key="later", key="rebuild:later")
    stale = _invoke(*_shadow_args(data_dir, legacy, classification, first_before))
    assert stale.exit_code == 1
    assert "projection is stale" in stale.stdout

    second_before = _action_watermark(kernel)
    second = _json(
        _invoke(
            "rebuild-projection",
            "--data-dir",
            str(data_dir),
            "--as-of",
            AT.isoformat(),
            "--built-at",
            "2026-08-24T10:10:00+00:00",
        )
    )
    assert second["source_high_watermark"] == second_before
    assert _action_watermark(kernel) == second_before

    shadow = _json(
        _invoke(
            *_shadow_args(
                data_dir,
                legacy,
                classification,
                int(second["source_high_watermark"]),
            )
        )
    )
    assert shadow["status"] == "committed"


def test_rebuild_projection_rejects_naive_time_and_uninitialized_root(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    naive = _invoke(
        "rebuild-projection",
        "--data-dir",
        str(data_dir),
        "--as-of",
        "2026-08-24T10:00:00",
        "--built-at",
        AT.isoformat(),
    )
    assert naive.exit_code == 1
    assert "timestamp must be timezone-aware" in naive.stdout

    absent = _invoke(
        "rebuild-projection",
        "--data-dir",
        str(tmp_path / "absent"),
        "--as-of",
        AT.isoformat(),
        "--built-at",
        AT.isoformat(),
    )
    assert absent.exit_code == 1
    assert "ontology must be initialized" in absent.stdout
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_scoreboard_projection_cli.py -v
```

Expected: both tests fail because Typer reports `No such command 'rebuild-projection'`.

### Task 2: Implement the build-only command

**Files:**
- Modify: `nutmeg/interfaces/cli/scoreboard.py`
- Test: `tests/product/test_scoreboard_projection_cli.py`

- [x] **Step 1: Add the projection request import and command**

Add:

```python
from nutmeg.analytics.calibrate_flow import CalibrateRequest
```

Register the command before `shadow`:

```python
@scoreboard_app.command("rebuild-projection")
def scoreboard_rebuild_projection(
    data_dir: Path = _DATA_DIR_OPTION,
    as_of: str = _cli.typer.Option(..., "--as-of"),
    built_at: str = _cli.typer.Option(..., "--built-at"),
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        normalized_as_of = _at(as_of).isoformat()
        normalized_built_at = _at(built_at).isoformat()
        result = kernel.calibrate.build(
            CalibrateRequest(
                as_of=normalized_as_of,
                built_at=normalized_built_at,
            )
        )
        if result.status != "succeeded":
            raise ScoreboardAuthorityError(
                f"scoreboard projection rebuild failed: {result.run_id}"
            )
        _emit(
            {
                "status": result.status,
                "run_id": result.run_id,
                "projection_version": "sb-v1",
                "source_high_watermark": result.high_watermark,
                "counts": {
                    "scorecards": result.scorecard_count,
                    "factor_estimates": result.factor_estimate_count,
                    "lifecycle_proposals": result.lifecycle_proposal_count,
                    "regime_vectors": result.regime_vector_count,
                },
                "targets": {
                    "data_dir": str(resolved),
                    "ontology_db": str(kernel.paths.database),
                    "analytics_db": str(kernel.paths.analytics),
                },
            }
        )
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)
```

- [x] **Step 2: Run focused tests and verify GREEN**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_scoreboard_projection_cli.py -v
```

Expected: `2 passed`; the first test demonstrates stale before rebuild and a committed
shadow after rebuild.

- [x] **Step 3: Run adjacent scoreboard and analytics tests**

Run:

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_cli.py \
  tests/scoreboard/test_authority.py \
  tests/analytics/test_calibrate_flow.py \
  tests/analytics/test_scoreboard_projection.py -q
```

Expected: all selected tests pass.

- [x] **Step 4: Commit the implementation**

```bash
git add nutmeg/interfaces/cli/scoreboard.py \
  tests/product/test_scoreboard_projection_cli.py
UV_FROZEN=1 git commit -m \
  "fix(scoreboard): expose build-only projection rebuild"
```

The commit body must record the reason: the legacy calibrate command is a JSONL operation,
while M5 projection freshness belongs to an explicit ontology build command.

### Task 3: Document the public M5 sequence and verify the package

**Files:**
- Modify: `docs/nutmeg-intelligence-os-m5-operations.md`

- [x] **Step 1: Replace the direct-service gap with the CLI sequence**

In section 3, retain the warning against legacy `decision-calibrate` and add:

```bash
UV_FROZEN=1 uv run nutmeg scoreboard rebuild-projection \
  --data-dir /absolute/path/to/isolated-data \
  --as-of 2026-08-24T10:05:00+08:00 \
  --built-at 2026-08-24T10:05:00+08:00
```

State that `source_high_watermark` and `projection_version` from the canonical JSON output
are the exact values passed to the following `scoreboard shadow` invocation.

- [x] **Step 2: Run formatting and package tests**

Run:

```bash
UV_FROZEN=1 uv run ruff check nutmeg/interfaces/cli/scoreboard.py \
  tests/product/test_scoreboard_projection_cli.py
UV_FROZEN=1 uv run pytest tests/product/ tests/scoreboard/ tests/analytics/ -q
git diff --check main...HEAD
git diff --check
```

Expected: ruff reports `All checks passed`; pytest reports zero failures; both diff checks
produce no output.

- [x] **Step 3: Smoke-test CLI help**

Run:

```bash
UV_FROZEN=1 uv run nutmeg scoreboard rebuild-projection --help
```

Expected: help lists required `--data-dir`, `--as-of`, and `--built-at` options.

- [x] **Step 4: Commit documentation**

```bash
git add docs/nutmeg-intelligence-os-m5-operations.md
UV_FROZEN=1 git commit -m "docs(scoreboard): document projection rebuild order"
```

## Execution Record (2026-08-28)

- `uv run pytest tests/product/test_scoreboard_projection_cli.py -v`: 2 passed.
- `uv run ruff check .`: All checks passed; `uv run pytest -q`: 1,390 tests
  collected, exit 0.
- Isolated CLI chain: the pre-rebuild shadow exited 1 with `projection is stale`;
  `scoreboard rebuild-projection` preserved the Action high-watermark and returned
  the new source high-watermark; the immediately following shadow was `committed`.
- Option 1 was selected because legacy `decision-calibrate` owns the JSONL path,
  while M5 freshness belongs to an explicit build-only ontology command. The reason
  is recorded in implementation commit `14f6940`.
- The shared schema-15 backup-test baseline fix is commit `9a21dac` on this branch.

## Explicit exclusions

- Do not run any command against `.nutmeg-data` during implementation or verification.
- Do not run `scoreboard cutover`, export, Telegram dispatch, or launchd operations.
- Do not change legacy `decision-calibrate`, `CalibrateService`, projectors, schema, or Actions.
- Do not modify or stage the root worktree's scheduler files or handoff document.
