from __future__ import annotations

from dataclasses import replace

from nutmeg.discovery.tournament_scores import ReplayCellEvidence, score_replay


def _evidence(**changes: object) -> ReplayCellEvidence:
    base = ReplayCellEvidence(
        trace_hash="trace-1",
        expected_trace_hash="trace-1",
        selected_evaluations=(
            {
                "eligible_band_count": 1,
                "best_objective_probability_by_band": {"10x": "0.62"},
                "distinct_valid_candidate_count_capped": 2,
            },
        ),
        node_count=2,
        rounds=1,
        retries=0,
        wall_seconds="1.25",
        candidate_generation_count=5,
        effective_parallelism="1",
    )
    return replace(base, **changes)


def test_scored_cell_preserves_quality_cost_and_parallelism():
    result = score_replay(_evidence())

    assert result.disqualified is False
    assert result.exclusion_reason is None
    assert result.score_vector["eligible_band_count"] == "1"
    assert result.score_vector["best_objective_probability_by_band"] == {"10x": "0.62"}
    assert result.score_vector["node_count"] == "2"
    assert result.score_vector["wall_seconds"] == "1.25"
    assert result.score_vector["candidate_generation_count"] == "5"
    assert result.score_vector["failure_recovery_rate"] == "1"


def test_safety_violation_disqualifies_even_with_best_quality():
    result = score_replay(_evidence(permission_breach=True))

    assert result.disqualified is True
    assert result.exclusion_reason == "permission_breach"


def test_missing_cost_remains_unknown_and_cannot_be_read_as_zero():
    result = score_replay(_evidence(wall_seconds=None, candidate_generation_count=None))

    assert result.score_vector["wall_seconds"] is None
    assert result.score_vector["candidate_generation_count"] is None
    assert result.score_vector["node_count"] == "2"


def test_unavailable_branch_and_no_solution_are_explicit_failed_outcomes():
    unavailable = score_replay(
        _evidence(selected_evaluations=(), branch_unavailable=True, failure_codes=("timeout",))
    )
    assert unavailable.disqualified is False
    assert unavailable.exclusion_reason == "branch_unavailable"
    assert unavailable.score_vector["failure_recovery_rate"] == "0"
    assert unavailable.score_vector["best_objective_probability_by_band"] == {}

    no_solution = score_replay(_evidence(selected_evaluations=()))
    assert no_solution.exclusion_reason == "no_solution"


def test_invalid_output_and_replay_hash_mismatch_are_disqualified():
    invalid = score_replay(_evidence(invalid_selected=True))
    mismatch = score_replay(_evidence(expected_trace_hash="other"))

    assert (invalid.disqualified, invalid.exclusion_reason) == (True, "invalid_selected")
    assert (mismatch.disqualified, mismatch.exclusion_reason) == (True, "trace_hash_mismatch")


def test_malformed_evaluation_is_an_explicit_invalid_output_not_a_crash():
    result = score_replay(_evidence(selected_evaluations=({"eligible_band_count": "Infinity"},)))

    assert (result.disqualified, result.exclusion_reason) == (True, "invalid_output")
    assert result.score_vector["eligible_band_count"] is None
    assert result.score_vector["wall_seconds"] == "1.25"


def test_quality_probability_outside_probability_range_is_invalid():
    result = score_replay(
        _evidence(
            selected_evaluations=(
                {
                    "eligible_band_count": 1,
                    "best_objective_probability_by_band": {"10x": "1.2"},
                    "distinct_valid_candidate_count_capped": 1,
                },
            )
        )
    )

    assert (result.disqualified, result.exclusion_reason) == (True, "invalid_output")
