from __future__ import annotations

import pytest

from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_board_workflow import JczqBoardWorkflow
from tests.ontology.operator.test_no_ticket_actions import (
    _fixture,
    _request,
)


def test_close_requires_exactly_one_formal_terminal_state(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    action_service = ActionService(lambda: OntologyUnitOfWork(fixture.engine))
    workflow = JczqBoardWorkflow(action_service)

    with pytest.raises(ValueError, match="terminal decision is missing"):
        workflow.require_terminal_state("2026-09-04")

    fixture.actions.record_no_ticket(_request(fixture))
    terminal = workflow.require_terminal_state("2026-09-04")

    assert terminal.kind == "no_ticket"
    assert terminal.no_ticket_revision_id is not None
    assert terminal.selection_revision_id is None
