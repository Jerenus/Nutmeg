from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from nutmeg.product.jczq_board_workflow import JczqBoardWorkflow
from nutmeg.product.jczq_compatibility import JczqCompatibilityProjector
from tests.product.operator_v2.test_deployment_replay import _selected_fixture


def test_projection_contains_source_revision_ids(tmp_path) -> None:
    workspace = tmp_path / "ontology"
    workspace.mkdir()
    fixture, _queries, selection_id = _selected_fixture(workspace)
    output_dir = tmp_path / "jczq"
    projector = JczqCompatibilityProjector(
        fixture.judgment.action_service,
        output_dir=output_dir,
    )

    result = projector.export_day("2026-09-04")

    assert result.reads[0]["forecast_revision_id"].startswith("fr-")
    assert result.reads[0]["judgment_revision_id"].startswith(
        "operator-match-judgment-"
    )
    assert result.handoff["candidate_set_revision_id"].startswith(
        "operator-candidate-set-"
    )
    assert result.handoff["selection_revision_id"] == selection_id
    day_dir = output_dir / "daily" / "2026-09-04"
    assert json.loads((day_dir / "reads.json").read_text()) == result.reads
    assert json.loads((day_dir / "legs.json").read_text()) == result.legs
    assert json.loads((day_dir / "nutmeg-handoff.json").read_text()) == result.handoff
    projector.verify_day("2026-09-04")


def test_selected_terminal_rejects_an_audit_incomplete_candidate() -> None:
    selection = SimpleNamespace(
        candidate_selection_id="selection-1",
        candidate_set_revision_id="set-1",
        candidate_revision_id="candidate-1",
    )
    candidate = SimpleNamespace(
        partition="eligible",
        deployable=0,
        leg_audit_completed=1,
        prescription_audit_completed=1,
        budget_check_completed=1,
        deployment_report_completed=0,
    )

    class _ActionService:
        @contextmanager
        def unit_of_work(self):
            yield SimpleNamespace(
                operator_decision=SimpleNamespace(
                    current_candidate_selections_for_task_family=lambda _task: (
                        selection,
                    )
                ),
                operator_result=SimpleNamespace(
                    current_no_ticket_revisions_for_task_family=lambda _task: (),
                    candidate=lambda _candidate_id: candidate,
                ),
            )

    workflow = JczqBoardWorkflow(_ActionService())

    with pytest.raises(ValueError, match="terminal decision audit is incomplete"):
        workflow.require_terminal_state("2026-09-04")
