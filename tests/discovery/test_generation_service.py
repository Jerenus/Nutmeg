from __future__ import annotations

from types import SimpleNamespace

from nutmeg.discovery.generation_service import GenerationService
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_generator_evolution import _context, _ready
from tests.ontology.test_discovery_policy_actions import _registration, _rig


def test_service_fails_closed_before_building_context_or_invoking_generator(tmp_path, monkeypatch):
    _actions, engine = _rig(tmp_path)
    service = GenerationService(engine)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("generator or development context accessed below gate")

    monkeypatch.setattr("nutmeg.discovery.generation_service.generate_evolution", unexpected)
    monkeypatch.setattr(service, "_context", unexpected)
    result = service.generate("bounded_evolution", round_id="blocked-1", seed=7)
    assert result.candidate_hashes == ()
    assert "effective_sample_size" in result.blocking_metrics
    with OntologyUnitOfWork(engine) as uow:
        row = uow.discovery.generation_round("blocked-1")
        assert row.status == "blocked"
        assert row.generation_cost == {"attempts": 0}


def test_service_rejects_disabled_generator_families(tmp_path):
    _actions, engine = _rig(tmp_path)
    for family in ("workflow_search", "tree_search"):
        try:
            GenerationService(engine).generate(family, round_id=family, seed=7)
        except ValueError as exc:
            assert "unsupported" in str(exc)
        else:
            raise AssertionError("disabled generator was accepted")


def test_synthetic_seeded_round_receipt_repeats_without_registration(tmp_path, monkeypatch):
    actions, engine = _rig(tmp_path)
    assert actions.register_policy(_registration()).status is ActionStatus.COMMITTED
    from nutmeg.discovery.generation_contracts import EligibleParent

    context = _context().model_copy(
        update={
            "eligible_parents": (
                EligibleParent(
                    policy_revision_id="policy-1",
                    disposition="incumbent",
                    lineage_root="policy-1",
                    template_order=("1x1", "2x1"),
                    batch_limit=1,
                ),
            )
        }
    )
    monkeypatch.setattr(
        "nutmeg.discovery.generation_service.DiscoveryReadService.readiness", lambda self: _ready()
    )
    monkeypatch.setattr(GenerationService, "_context", lambda self, **kwargs: context)
    service = GenerationService(engine)
    first = service.generate(
        "bounded_evolution",
        round_id="synthetic-1",
        seed=7,
        development_cutoff="2026-09-01T00:00:00+00:00",
    )
    second = service.generate(
        "bounded_evolution",
        round_id="synthetic-2",
        seed=7,
        development_cutoff="2026-09-01T00:00:00+00:00",
    )
    assert first.candidate_hashes == second.candidate_hashes
    with OntologyUnitOfWork(engine) as uow:
        a = uow.discovery.generation_round(first.round_id)
        b = uow.discovery.generation_round(second.round_id)
        assert (a.trace_hash, a.input_manifest_hash, a.generation_cost) == (
            b.trace_hash,
            b.input_manifest_hash,
            b.generation_cost,
        )
        assert a.seed == 7
        assert uow.discovery.policy(a.trace["proposals"][0]["policy_revision_id"]) is None


def test_generated_archive_parent_uses_recorded_validated_artifact():
    from nutmeg.discovery.generation_service import parent_parameters
    from nutmeg.ontology.discovery.models import canonical_hash
    from tests.discovery.test_generation_contracts import _document

    artifact = _document()
    policy = SimpleNamespace(
        policy_revision_id=artifact["policy_revision_id"],
        source_artifact_hash=canonical_hash(artifact),
        generator_descriptors={"generation_round_id": "round-1"},
        configuration={},
    )
    repo = SimpleNamespace(
        generation_round=lambda _: SimpleNamespace(trace={"proposals": [artifact]})
    )
    assert parent_parameters(policy, repo) == (("1x1", "2x1"), 2)
