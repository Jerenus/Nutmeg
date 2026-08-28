import json
import math

import pytest
from typer.testing import CliRunner

from nutmeg.decision.zucai_deployment import (
    DeploymentGateState,
    evaluate_deployment_gate,
    format_deployment_gate,
)
from nutmeg.decision.zucai_official import OfficialRenjiuHistory
from nutmeg.interfaces.cli import app

_OFFICIAL_26104_COHORT = [
    ("26103", 3296, 2744, 14135916),
    ("26102", 408, 21018, 13399134),
    ("26101", 209, 46573, 15209134),
    ("26100", 3296, 2422, 12478054),
    ("26099", 1505, 4937, 11611826),
    ("26098", 987, 7956, 12270216),
    ("26097", 760, 10904, 12949594),
    ("26096", 501, 16097, 12601364),
    ("26095", 250, 30607, 11956014),
    ("26094", 652, 11533, 11749264),
    ("26093", 3071, 2510, 12047162),
    ("26092", 2107, 3838, 12635578),
    ("26091", 5774, 1626, 14674292),
    ("26090", 7194, 1305, 14675304),
]


def _history():
    return [
        OfficialRenjiuHistory(
            issue=issue,
            draw_date="2026-08-01",
            stake_count=count,
            stake_amount=float(amount),
            sale_amount=float(sale),
        )
        for issue, count, amount, sale in _OFFICIAL_26104_COHORT
    ]


def _payload(**changes):
    payload = {
        "issue": "26104",
        "period_cap_yuan": 1600,
        "history_as_of_issue": "26104",
        "history_window": 14,
        "candidates": [{
            "id": "M1296",
            "stake_yuan": 1296,
            "hit_probability": 1296 / 6097,
        }],
    }
    payload.update(changes)
    return payload


def test_gate_selects_max_probability_inside_cap_and_reports_arithmetic():
    payload = _payload(
        period_cap_yuan=400,
        candidates=[
            {"id": "V288", "stake_yuan": 288, "hit_probability": 0.14},
            {"id": "V384", "stake_yuan": 384, "hit_probability": 0.16},
            {"id": "R432", "stake_yuan": 432, "hit_probability": 0.19},
        ],
    )

    result = evaluate_deployment_gate(payload, _history())

    assert result.selected_id == "V384"
    assert result.capital_utilization == pytest.approx(0.96)
    assert result.break_even_bonus == pytest.approx(2400.0)
    assert result.median_bonus == pytest.approx(6446.5)
    assert result.break_even_to_median == pytest.approx(2400 / 6446.5)
    assert result.equivalent_max_winning_stakes == math.floor(
        result.median_sale_amount * 0.64 / 2400
    )
    assert result.excluded_over_cap == ("R432",)


def test_gate_breaks_equal_probability_tie_by_lower_stake_then_id():
    result = evaluate_deployment_gate(
        _payload(candidates=[
            {"id": "B", "stake_yuan": 300, "hit_probability": 0.20},
            {"id": "A", "stake_yuan": 300, "hit_probability": 0.20},
            {"id": "C", "stake_yuan": 320, "hit_probability": 0.20},
        ]),
        _history(),
    )
    assert result.selected_id == "A"


@pytest.mark.parametrize(
    ("ratio", "state", "exit_code"),
    [
        (0.95, DeploymentGateState.PASS, 0),
        (0.9501, DeploymentGateState.REVIEW, 2),
        (2.1999, DeploymentGateState.REVIEW, 2),
        (2.2, DeploymentGateState.REDUCE_OR_EMPTY, 3),
    ],
)
def test_gate_exact_ratio_boundaries(ratio, state, exit_code):
    median = 1000.0
    history = [OfficialRenjiuHistory("1", "", 640, median, 1_000_000)]
    payload = _payload(
        history_as_of_issue="2",
        history_window=1,
        candidates=[{
            "id": "boundary",
            "stake_yuan": 100,
            "hit_probability": 100 / (median * ratio),
        }],
    )
    result = evaluate_deployment_gate(payload, history)
    assert result.state is state
    assert result.exit_code == exit_code


@pytest.mark.parametrize(
    "changes",
    [
        {"period_cap_yuan": 0},
        {"history_window": 0},
        {"candidates": []},
        {"candidates": [{"id": "bad", "stake_yuan": 10, "hit_probability": 0}]},
        {"candidates": [{"id": "over", "stake_yuan": 2000, "hit_probability": 0.5}]},
    ],
)
def test_gate_rejects_invalid_or_absent_cap_candidate(changes):
    with pytest.raises(ValueError):
        evaluate_deployment_gate(_payload(**changes), _history())


def test_gate_rejects_insufficient_official_history():
    with pytest.raises(ValueError, match="history_window"):
        evaluate_deployment_gate(_payload(history_window=15), _history())


def test_26103_replay_returns_reduce_or_empty_like_actual_empty_slate():
    result = evaluate_deployment_gate(
        _payload(
            issue="26103",
            period_cap_yuan=400,
            candidates=[{
                "id": "cap-optimal",
                "stake_yuan": 400,
                "hit_probability": 400 / 14412,
            }],
        ),
        _history(),
    )
    assert result.state is DeploymentGateState.REDUCE_OR_EMPTY
    assert result.break_even_to_median == pytest.approx(2.24, abs=0.01)
    assert "丢场式减注" in format_deployment_gate(result)
    assert "无合格减注版" in format_deployment_gate(result)


def test_26104_replay_passes_at_recorded_point_95_compromise():
    result = evaluate_deployment_gate(_payload(), _history())
    assert result.state is DeploymentGateState.PASS
    assert result.break_even_bonus == pytest.approx(6097)
    assert result.break_even_to_median == pytest.approx(0.95, abs=0.01)
    assert result.capital_utilization == pytest.approx(0.81)


def _write_cli_files(tmp_path, *, ratio: float):
    median = 1000.0
    gate_file = tmp_path / "gate.json"
    gate_file.write_text(json.dumps({
        "issue": "26104",
        "period_cap_yuan": 100,
        "history_as_of_issue": "26104",
        "history_window": 1,
        "candidates": [{
            "id": "candidate",
            "stake_yuan": 100,
            "hit_probability": 100 / (median * ratio),
        }],
    }), encoding="utf-8")
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "value": {"list": [{
            "lotteryDrawNum": "26103",
            "lotteryDrawTime": "2026-08-26",
            "lotteryDrawResult": "* * * * * * * * * * * * * *",
            "prizeLevelListRj": [{
                "prizeLevel": "任选9场",
                "stakeCount": "640",
                "stakeAmount": "1,000",
            }],
            "totalSaleAmountRj": "1,000,000",
        }]},
    }), encoding="utf-8")
    return gate_file, history_file


@pytest.mark.parametrize(("ratio", "exit_code"), [(0.95, 0), (1.2, 2), (2.2, 3)])
def test_deployment_gate_cli_returns_governed_exit_codes(tmp_path, ratio, exit_code):
    gate_file, history_file = _write_cli_files(tmp_path, ratio=ratio)

    result = CliRunner().invoke(app, [
        "zucai-deployment-gate",
        "--gate-file", str(gate_file),
        "--official-history-file", str(history_file),
        "--json",
    ])

    assert result.exit_code == exit_code
    payload = json.loads(result.stdout)
    assert payload["exit_code"] == exit_code
    assert payload["selected_id"] == "candidate"


def test_deployment_gate_cli_returns_one_for_malformed_official_history(tmp_path):
    gate_file, history_file = _write_cli_files(tmp_path, ratio=0.95)
    history_file.write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(app, [
        "zucai-deployment-gate",
        "--gate-file", str(gate_file),
        "--official-history-file", str(history_file),
    ])

    assert result.exit_code == 1
    assert "official history" in result.stdout
