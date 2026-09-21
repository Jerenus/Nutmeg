from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from nutmeg.discovery.online_inputs import (
    freeze_structural_input,
    read_structural_input,
    read_structural_input_from_database,
)
from tests.ontology.operator.test_candidate_actions import (
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import AT
from tests.product.operator_v2.test_candidate_bands import _input_with_combined_odds


def _references():
    return (
        {
            "kind": "forecast",
            "id": "forecast-1",
            "source_revision": "f-1",
            "captured_at": "2026-09-21T06:00:00+00:00",
        },
        {
            "kind": "prescription",
            "id": "prescription-1",
            "source_revision": "p-1",
            "captured_at": "2026-09-21T06:01:00+00:00",
        },
        {
            "kind": "quote",
            "id": "quote-3",
            "source_revision": "q-1",
            "captured_at": "2026-09-21T06:02:00+00:00",
        },
        {
            "kind": "quote",
            "id": "quote-1",
            "source_revision": "q-1",
            "captured_at": "2026-09-21T06:02:00+00:00",
        },
        {
            "kind": "quote",
            "id": "quote-0",
            "source_revision": "q-1",
            "captured_at": "2026-09-21T06:02:00+00:00",
        },
    )


def _freeze(**changes):
    values = dict(
        candidate_input=_input_with_combined_odds("10.000000000000"),
        references=_references(),
        business_date="2026-09-21",
        task_snapshot_hash="task-sha",
        slate_revision_id="slate-1",
        board_slate_revision_id="slate-1",
        cutoff_at="2026-09-21T07:00:00+00:00",
        audit_policy_revision="audit-v1",
    )
    values.update(changes)
    return freeze_structural_input(**values)


def test_snapshot_is_stable_and_contains_ordered_unique_shards():
    snapshot = _freeze()
    assert snapshot.manifest_hash == _freeze().manifest_hash
    assert snapshot.template_ids == ("1x1",)
    assert next(r.source_revision for r in snapshot.references if r.kind == "forecast") == "f-1"


@pytest.mark.parametrize(
    "changed",
    [
        {
            "kind": "quote",
            "id": "quote-new",
            "source_revision": "q-new",
            "captured_at": "2026-09-21T08:00:00+00:00",
        },
        {
            "kind": "quote",
            "id": "quote-new",
            "source_revision": "",
            "captured_at": "2026-09-21T06:00:00+00:00",
        },
    ],
)
def test_snapshot_refuses_post_cutoff_or_unknown_provenance(changed):
    with pytest.raises(ValueError, match="cutoff|provenance"):
        _freeze(references=(*_references(), changed))


def test_snapshot_refuses_wrong_board_or_missing_authority():
    with pytest.raises(ValueError, match="board"):
        _freeze(board_slate_revision_id="other-slate")
    with pytest.raises(ValueError, match="prescription"):
        _freeze(references=tuple(r for r in _references() if r["kind"] != "prescription"))
    with pytest.raises(ValueError, match="forecast"):
        _freeze(references=tuple(r for r in _references() if r["kind"] != "forecast"))
    with pytest.raises(ValueError, match="audit"):
        _freeze(audit_policy_revision="")


def test_snapshot_refuses_missing_quote_and_duplicate_template():
    with pytest.raises(ValueError, match="quote"):
        _freeze(references=tuple(r for r in _references() if r["id"] != "quote-3"))
    candidate_input = _input_with_combined_odds("10.000000000000")
    with pytest.raises(ValueError, match="template"):
        _freeze(candidate_input=replace(candidate_input, templates=()))


def _source_uow(monkeypatch):
    generation = SimpleNamespace(
        requested_at="2026-09-21T06:00:00+00:00",
        slate_revision_id="slate-1",
        task_snapshot_hash="task-sha",
        judgment_prescription_revision_id="prescription-1",
        task_evidence_bundle_revision_id="bundle-1",
    )
    prescription = SimpleNamespace(
        judgment_prescription_revision_id="prescription-1",
        slate_revision_id="slate-1",
        task_snapshot_hash="task-sha",
        content_hash="prescription-hash",
        created_at="2026-09-21T06:00:00+00:00",
    )
    judgment = SimpleNamespace(forecast_revision_id="forecast-1")
    uow = SimpleNamespace(
        operator_decision=SimpleNamespace(
            candidate_generation_request=Mock(return_value=generation),
            judgment_prescription_revision=Mock(return_value=prescription),
            judgment_prescription_items=Mock(
                return_value=(SimpleNamespace(operator_match_judgment_revision_id="j-1"),)
            ),
            operator_match_judgment_revision=Mock(return_value=judgment),
        ),
        operator_sale=SimpleNamespace(
            slate_revision=Mock(return_value=SimpleNamespace(business_key="2026-09-21"))
        ),
        operator_result=SimpleNamespace(
            candidate_set_for_request=Mock(return_value=SimpleNamespace(
                audit_policy_version="operator-candidate-audit-v1",
                slate_revision_id="slate-1",
                task_snapshot_hash="task-sha",
                candidate_set_revision_id="candidate-set-1",
                content_hash="candidate-set-hash",
                created_at="2026-09-21T06:00:00+00:00",
            ))
        ),
        market=SimpleNamespace(quote=Mock()),
        connection=Mock(),
    )
    uow.connection.execute.return_value.mappings.return_value.first.return_value = {
        "status": "draft"
    }
    monkeypatch.setattr(
        "nutmeg.product.operator_workers._candidate_generation_inputs",
        lambda *_: (_input_with_combined_odds("10.000000000000"), None, (), None),
    )
    return uow


def test_read_adapter_rejects_uncommitted_forecast(monkeypatch):
    uow = _source_uow(monkeypatch)
    with pytest.raises(ValueError, match="committed forecast"):
        read_structural_input(uow, "request-1", cutoff_at="2026-09-21T07:00:00+00:00")


def test_read_adapter_rejects_inactive_quote(monkeypatch):
    uow = _source_uow(monkeypatch)
    uow.connection.execute.return_value.mappings.return_value.first.return_value = {
        "status": "committed", "forecast_revision_id": "forecast-1", "revision_no": 1,
        "made_at": "2026-09-21T06:00:00+00:00",
    }
    uow.market.quote.side_effect = lambda quote_id: SimpleNamespace(
        quote_id=quote_id,
        quote_status="withdrawn",
        captured_at="2026-09-21T06:00:00+00:00",
    )
    with pytest.raises(ValueError, match="quote"):
        read_structural_input(uow, "request-1", cutoff_at="2026-09-21T07:00:00+00:00")


def test_read_adapter_refuses_missing_registered_audit_policy():
    generation = SimpleNamespace(
        requested_at="2026-09-21T06:00:00+00:00",
        slate_revision_id="slate-1",
        judgment_prescription_revision_id="prescription-1",
        task_snapshot_hash="task-sha",
    )
    uow = SimpleNamespace(
        operator_decision=SimpleNamespace(
            candidate_generation_request=Mock(return_value=generation),
            judgment_prescription_revision=Mock(return_value=SimpleNamespace(
                slate_revision_id="slate-1", task_snapshot_hash="task-sha"
            )),
        ),
        operator_sale=SimpleNamespace(slate_revision=Mock(return_value=object())),
        operator_result=SimpleNamespace(candidate_set_for_request=Mock(return_value=None)),
    )
    with pytest.raises(ValueError, match="audit policy"):
        read_structural_input(uow, "request-1", cutoff_at="2026-09-21T07:00:00+00:00")


def test_read_adapter_refuses_request_created_after_cutoff():
    uow = SimpleNamespace(operator_decision=SimpleNamespace(
        candidate_generation_request=Mock(return_value=SimpleNamespace(
            requested_at="2026-09-21T08:00:00+00:00"
        ))
    ))
    with pytest.raises(ValueError, match="cutoff"):
        read_structural_input(uow, "request-new", cutoff_at="2026-09-21T07:00:00+00:00")


def test_source_connection_is_query_only_and_does_not_modify_database(tmp_path, monkeypatch):
    database = tmp_path / "business.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE protected (id INTEGER)")
    original = database.read_bytes()

    def try_write(uow, *_args, **_kwargs):
        uow.connection.exec_driver_sql("INSERT INTO protected (id) VALUES (1)")

    monkeypatch.setattr("nutmeg.discovery.online_inputs.read_structural_input", try_write)
    with pytest.raises(OperationalError, match="readonly"):
        read_structural_input_from_database(
            database, "request-1", cutoff_at="2026-09-21T07:00:00+00:00"
        )
    assert database.read_bytes() == original


def test_real_candidate_lineage_freezes_from_read_only_source(tmp_path):
    fixture = _ready_fixture(tmp_path)
    outcome = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    request_id = outcome.result_refs[0].object_id
    _generate(fixture, request_id=request_id)
    database = tmp_path / "ontology.db"
    assert database.is_file()
    before = database.read_bytes()
    first = read_structural_input_from_database(
        database, request_id, cutoff_at=(AT + timedelta(seconds=10)).isoformat()
    )
    second = read_structural_input_from_database(
        database, request_id, cutoff_at=(AT + timedelta(seconds=10)).isoformat()
    )
    assert first.manifest_hash == second.manifest_hash
    assert first.audit_offers
    assert first.template_ids
    assert first.source_identity == str(database.resolve())
    assert database.read_bytes() == before
