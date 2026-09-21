from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.selection_contract import load_selection_contract
from nutmeg.discovery.tournament_selector import SelectionCell, select_winner

ROOT = Path(__file__).resolve().parents[2]
PILOT = load_pilot_contract(ROOT / "experiments/discovery/structural-candidate-v1.contract.json")
CONTRACT = load_selection_contract(
    ROOT / "experiments/discovery/structural-selection-v1.contract.json", PILOT
)


def _vector(quality: int = 1, **changes: object) -> dict[str, object]:
    return {
        "invariant_violation_count": "0",
        "invalid_selected_count": "0",
        "eligible_band_count": str(quality),
        "best_objective_probability_by_band": {"10x": "0.5"},
        "distinct_valid_candidate_count_capped": "2",
        "failure_recovery_rate": "1",
        "node_count": "2",
        "wall_seconds": "1",
        "effective_parallelism": "1",
        **changes,
    }


def _matrix(*, challenger_quality: int = 2) -> tuple[SelectionCell, ...]:
    return tuple(
        SelectionCell(
            policy_revision_id=policy,
            world_id=world,
            pool_role=role,
            strata=(stratum,),
            score_vector=_vector(1 if policy == "incumbent" else challenger_quality),
            disqualified=False,
            exclusion_reason=None,
            trace_hash=f"{policy}:{world}",
        )
        for world, role, stratum in (
            ("world-dev", "development", "board_size:small"),
            ("world-hold", "holdout", "board_size:small"),
        )
        for policy in ("incumbent", "challenger")
    )


def _select(cells: tuple[SelectionCell, ...]):
    return select_winner(CONTRACT, "incumbent", ("incumbent", "challenger"), cells)


def test_material_quality_gain_wins_with_stable_order_independent_proof():
    cells = _matrix()
    selected = _select(cells)

    assert selected.winner_policy_revision_id == "challenger"
    assert selected.proof_hash == _select(tuple(reversed(cells))).proof_hash


def test_exact_tie_and_submaterial_gain_keep_incumbent():
    assert _select(_matrix(challenger_quality=1)).winner_policy_revision_id == "incumbent"


def test_safety_failure_disqualifies_candidate_with_better_quality():
    cells = _matrix()
    bad = replace(cells[1], disqualified=True, exclusion_reason="permission_breach")

    selected = _select((cells[0], bad, *cells[2:]))
    assert selected.winner_policy_revision_id == "incumbent"
    assert selected.disqualification_reasons["challenger"] == "permission_breach"


def test_holdout_loss_brakes_development_gain():
    cells = tuple(
        replace(cell, score_vector=_vector(0))
        if cell.policy_revision_id == "challenger" and cell.pool_role == "holdout"
        else cell
        for cell in _matrix()
    )

    assert _select(cells).winner_policy_revision_id == "incumbent"


def test_unknown_cost_does_not_become_free_improvement():
    cells = tuple(
        replace(cell, score_vector=_vector(1, wall_seconds=None, node_count=None))
        if cell.policy_revision_id == "challenger"
        else cell
        for cell in _matrix(challenger_quality=1)
    )

    assert _select(cells).winner_policy_revision_id == "incumbent"


def test_missing_or_duplicate_matrix_cell_is_rejected():
    import pytest

    cells = _matrix()
    with pytest.raises(ValueError, match="matrix"):
        _select(cells[:-1])
    with pytest.raises(ValueError, match="matrix"):
        _select((*cells, cells[-1]))


def test_submaterial_quality_change_alone_cannot_promote():
    cells = tuple(
        replace(
            cell,
            score_vector=_vector(
                1,
                best_objective_probability_by_band={"10x": "0.5005"},
                node_count="2",
            ),
        )
        if cell.policy_revision_id == "challenger"
        else cell
        for cell in _matrix(challenger_quality=1)
    )

    assert _select(cells).winner_policy_revision_id == "incumbent"


def test_worst_stratum_decline_brakes_even_with_aggregate_gain():
    cells = list(_matrix())
    for policy in ("incumbent", "challenger"):
        for world, role in (("dev-large", "development"), ("hold-large", "holdout")):
            cells.append(
                SelectionCell(
                    policy_revision_id=policy,
                    world_id=world,
                    pool_role=role,
                    strata=("board_size:large",),
                    score_vector=_vector(1 if policy == "incumbent" else 4),
                    disqualified=False,
                    exclusion_reason=None,
                    trace_hash=f"{policy}:{world}",
                )
            )
    cells = [
        replace(cell, score_vector=_vector(0))
        if cell.policy_revision_id == "challenger" and "board_size:small" in cell.strata
        else cell
        for cell in cells
    ]

    result = _select(tuple(cells))
    assert result.winner_policy_revision_id == "incumbent"
    assert result.comparison_reasons["challenger"] == "worst_stratum_decline"


def test_best_of_multiple_challengers_wins_independent_of_candidate_order():
    cells = _matrix()
    stronger = tuple(
        replace(
            cell,
            policy_revision_id="stronger",
            trace_hash=f"stronger:{cell.world_id}",
            score_vector=_vector(3),
        )
        for cell in cells
        if cell.policy_revision_id == "challenger"
    )

    result = select_winner(
        CONTRACT,
        "incumbent",
        ("stronger", "incumbent", "challenger"),
        (*cells, *stronger),
    )
    assert result.winner_policy_revision_id == "stronger"
