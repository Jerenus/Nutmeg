from __future__ import annotations

from dataclasses import replace

import pytest

from nutmeg.discovery.online_adapter import execute_template_shard
from nutmeg.discovery.online_inputs import freeze_structural_input
from nutmeg.product.operator_candidates import (
    CandidateAuditFinding,
    CandidateSpaceLimitError,
    CandidateStructureTemplate,
    enumerate_band_candidates,
)
from nutmeg.product.operator_workers import _CandidateAuditOffer
from tests.discovery.test_online_inputs import _freeze, _references


def _snapshot():
    base = _freeze()
    audit = _CandidateAuditOffer(
        official_match_no="001",
        market_definition_id="md-had",
        belief=base.candidate_input.offers[0].probabilities,
        prior=base.candidate_input.offers[0].probabilities,
        prescribed_face_bundles=(frozenset({"3"}),),
        rule_ids=(),
    )
    return _freeze(audit_offers=(audit,))


def test_shard_only_enumerates_selected_templates():
    snapshot = _snapshot()
    other = CandidateStructureTemplate(
        kind="jczq_pass",
        structure_code="other",
        eligible_official_match_nos=("001",),
        required_offer_count=1,
        maximum_groups=1,
        pass_size=1,
    )
    snapshot = freeze_structural_input(
        candidate_input=replace(
            snapshot.candidate_input,
            templates=(*snapshot.candidate_input.templates, other),
        ),
        references=_references(),
        business_date=snapshot.business_date,
        task_snapshot_hash=snapshot.task_snapshot_hash,
        slate_revision_id=snapshot.slate_revision_id,
        board_slate_revision_id=snapshot.slate_revision_id,
        cutoff_at=snapshot.cutoff_at,
        audit_policy_revision=snapshot.audit_policy_revision,
        audit_offers=snapshot.audit_offers,
    )
    seen = []

    def enumerate_spy(inputs, **kwargs):
        seen.append((tuple(t.structure_code for t in inputs.templates), kwargs))
        return None

    failed = execute_template_shard(snapshot, ("1x1",), enumerate_fn=enumerate_spy)
    assert failed.diagnostic_codes == ("adapter_error", "ValueError")
    assert seen[0][0] == ("1x1",)
    assert seen[0][1]["set_kind"] == "judgment_bound"
    assert seen[0][1]["generator_version"] == "operator-candidate-v2-bands"


def test_no_feasible_candidate_is_explicit_and_metered():
    result = execute_template_shard(_snapshot(), ("1x1",))
    assert result.status in {"complete", "no_solution"}
    assert result.artifact_hash == result.artifact_manifest["content_hash"]
    assert result.resource_cost["wall_ms"] >= 0
    assert result.resource_cost["candidate_generation_count"] is not None
    assert result.artifact_manifest["snapshot_hash"] == _snapshot().manifest_hash


def test_unknown_shard_is_rejected_before_execution():
    with pytest.raises(ValueError, match="template"):
        execute_template_shard(_snapshot(), ("unregistered",))


def test_global_candidate_budget_is_passed_to_pure_enumerator():
    snapshot = _snapshot()
    seen = []

    def observe(inputs, **kwargs):
        seen.append(inputs.maximum_exhaustive_candidate_count)
        return enumerate_band_candidates(inputs, **kwargs)

    execute_template_shard(
        snapshot, ("1x1",), enumerate_fn=observe, candidate_count_limit=3
    )
    assert seen == [3]


def test_over_cap_is_explicit_failure_with_cost():
    def too_many(inputs, **kwargs):
        result = enumerate_band_candidates(inputs, **kwargs)
        band = result.by_band["10x"]
        many = replace(band, candidates=band.candidates * 21)
        return replace(result, by_band={**result.by_band, "10x": many})

    result = execute_template_shard(_snapshot(), ("1x1",), enumerate_fn=too_many)
    assert result.status == "failed"
    assert result.diagnostic_codes == ("over_cap",)
    assert result.resource_cost["wall_ms"] >= 0


def test_candidate_space_limit_is_not_silently_treated_as_empty():
    def over_limit(*_args, **_kwargs):
        raise CandidateSpaceLimitError(100, 10)

    result = execute_template_shard(_snapshot(), ("1x1",), enumerate_fn=over_limit)
    assert result.status == "failed"
    assert result.diagnostic_codes == ("candidate_space_over_cap",)
    assert result.resource_cost["candidate_generation_count"] is None


def test_no_solution_is_nonselectable():
    snapshot = _snapshot()
    offer = replace(
        snapshot.candidate_input.offers[0],
        booked_decimal_odds_by_face=(
            ("3", "2.500000000000"),
            ("1", "3.000000000000"),
            ("0", "4.000000000000"),
        ),
    )
    snapshot = freeze_structural_input(
        candidate_input=replace(snapshot.candidate_input, offers=(offer,)),
        references=_references(),
        business_date=snapshot.business_date,
        task_snapshot_hash=snapshot.task_snapshot_hash,
        slate_revision_id=snapshot.slate_revision_id,
        board_slate_revision_id=snapshot.slate_revision_id,
        cutoff_at=snapshot.cutoff_at,
        audit_policy_revision=snapshot.audit_policy_revision,
        audit_offers=snapshot.audit_offers,
    )
    result = execute_template_shard(snapshot, ("1x1",))
    assert result.status == "no_solution"
    assert result.selectable is False


def test_quality_ignores_audit_blocked_candidate_even_if_its_probability_is_higher():
    def include_blocked(inputs, **kwargs):
        result = enumerate_band_candidates(inputs, **kwargs)
        valid = result.by_band["10x"].candidates[0]
        blocked = replace(
            valid,
            content_hash="blocked",
            objective_probability_decimal="0.990000000000",
            audit_findings=(CandidateAuditFinding(
                finding_id="blocked-1", code="blocked", severity="ERROR", message="blocked"
            ),),
        )
        band = replace(result.by_band["10x"], candidates=(valid, blocked))
        return replace(result, candidates=(valid, blocked), by_band={**result.by_band, "10x": band})

    result = execute_template_shard(_snapshot(), ("1x1",), enumerate_fn=include_blocked)
    assert result.evaluation["best_objective_probability_by_band"]["10x"] != "0.990000000000"
    assert result.evaluation["distinct_valid_candidate_count_capped"] == 1
