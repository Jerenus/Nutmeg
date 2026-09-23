from __future__ import annotations

from dataclasses import replace

import pytest

from nutmeg.discovery.online_inputs import freeze_structural_input
from tests.discovery.test_candidate_bands import _input_with_combined_odds


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
