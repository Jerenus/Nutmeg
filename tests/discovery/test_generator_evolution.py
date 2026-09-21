from __future__ import annotations

from dataclasses import replace

import pytest

from nutmeg.discovery.generation_contracts import EligibleParent, GenerationContext
from nutmeg.discovery.generator_evolution import generate_evolution
from nutmeg.discovery.readiness import ReplayMetrics, assess_readiness
from tests.discovery.test_readiness import PILOT, _worlds


def _context():
    return GenerationContext(
        schema_version="1",
        generator_revision="bounded-evolution-v1",
        constraint_revision="structural-candidate-v1",
        development_worlds=(),
        eligible_parents=(
            EligibleParent(
                policy_revision_id="parent-a",
                disposition="incumbent",
                lineage_root="parent-a",
                template_order=("1x1", "2x1"),
                batch_limit=1,
            ),
        ),
        template_ids=("1x1", "2x1"),
        seed=7,
        candidate_cap=2,
        compute_budget=3,
        timeout_seconds=10,
    )


def _ready(worlds=None, replay=None):
    worlds = (
        worlds
        if worlds is not None
        else tuple(replace(w, failed_or_degraded=i < 3) for i, w in enumerate(_worlds(60)))
    )
    replay = replay if replay is not None else ReplayMetrics(True, 0.8, 0.1)
    return assess_readiness(worlds, PILOT.readiness, replay)


@pytest.mark.parametrize(
    "report,metric",
    [
        (_ready(_worlds(59)), "sealed_worlds"),
        (
            _ready(
                tuple(
                    replace(
                        w, task_snapshot_hash="same", slate_revision_id="same", business_date="same"
                    )
                    for w in _worlds(60)
                )
            ),
            "effective_sample_size",
        ),
        (_ready(_worlds(60), ReplayMetrics(True, 0.1, 0.1)), "action_overlap"),
        (_ready(_worlds(60)), "failed_or_degraded_worlds"),
        (_ready(replay=ReplayMetrics(True, 0.8, None)), "branch_unavailable_rate"),
    ],
)
def test_direct_evolution_is_blocked_on_every_failed_gate(report, metric):
    result = generate_evolution(_context(), report)
    assert result.proposals == ()
    assert metric in result.blocking_metrics
    assert result.cost == {"attempts": 0}


def test_seeded_evolution_reproduces_hashes_parentage_trace_and_budget():
    first = generate_evolution(_context(), _ready())
    assert first == generate_evolution(_context(), _ready())
    assert len(first.proposals) == 2
    assert first.cost == {"attempts": 2}
    assert all(p.parent_policy_revision_ids == ("parent-a",) for p in first.proposals)
    assert all(p.seed == 7 for p in first.proposals)
    assert first.status == "truncated"


def test_two_eligible_parents_can_recombine_with_complete_ordered_lineage():
    from nutmeg.discovery.generation_contracts import EligibleParent

    context = _context().model_copy(
        update={
            "template_ids": ("1x1", "2x1", "3x1"),
            "eligible_parents": (
                EligibleParent(
                    policy_revision_id="parent-a",
                    disposition="incumbent",
                    lineage_root="parent-a",
                    template_order=("1x1", "2x1"),
                    batch_limit=1,
                ),
                EligibleParent(
                    policy_revision_id="parent-b",
                    disposition="stepping_stone",
                    lineage_root="parent-b",
                    template_order=("3x1", "2x1"),
                    batch_limit=2,
                ),
            ),
        }
    )
    first = generate_evolution(context, _ready())
    assert first == generate_evolution(context, _ready())
    child = first.proposals[1]
    assert child.parent_policy_revision_ids == ("parent-a", "parent-b")
    assert set(child.program.template_order) == {"1x1", "2x1", "3x1"}


def test_evolution_stops_at_real_deadline_and_charges_attempt(monkeypatch):
    import nutmeg.discovery.generator_evolution as generator_module

    ticks = iter((0.0, 0.1, 1.1))
    monkeypatch.setattr(generator_module, "monotonic", lambda: next(ticks), raising=False)
    context = _context().model_copy(update={"timeout_seconds": 1})
    result = generate_evolution(context, _ready())
    assert result.status == "timeout"
    assert result.cost == {"attempts": 1}


def test_evolution_rejects_unsupported_family_and_frozen_parent_payload():
    with pytest.raises(ValueError, match="literal_error"):
        GenerationContext.model_validate(
            {**_context().model_dump(), "generator_revision": "workflow_search"}
        )
    with pytest.raises(ValueError, match="extra|forbidden"):
        EligibleParent.model_validate(
            {**_context().eligible_parents[0].model_dump(), "model_weights": {"x": 1}}
        )
