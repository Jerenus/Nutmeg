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
from nutmeg.decision.zucai_optimizer import optimize
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


def test_gate_selects_lowest_break_even_inside_cap_and_reports_arithmetic():
    payload = _payload(
        period_cap_yuan=400,
        candidates=[
            {"id": "V288", "stake_yuan": 288, "hit_probability": 0.14},
            {"id": "V384", "stake_yuan": 384, "hit_probability": 0.16},
            {"id": "R432", "stake_yuan": 432, "hit_probability": 0.19},
        ],
    )

    result = evaluate_deployment_gate(payload, _history())

    # 回本线：V288=¥2,057 < V384=¥2,400 → 新语义选 V288（旧 max-P 语义会选 V384）。
    assert result.selected_id == "V288"
    assert result.capital_utilization == pytest.approx(0.72)
    assert result.break_even_bonus == pytest.approx(288 / 0.14)
    assert result.median_bonus == pytest.approx(6446.5)
    assert result.break_even_to_median == pytest.approx((288 / 0.14) / 6446.5)
    assert result.equivalent_max_winning_stakes == math.floor(
        result.median_sale_amount * 0.64 / (288 / 0.14)
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
    # 固定 12 期窗口：12 行等值历史，中位仍为 median，仅检验比值分档边界。
    history = [
        OfficialRenjiuHistory(str(idx), "", 640, median, 1_000_000)
        for idx in range(1, 13)
    ]
    payload = _payload(
        issue="26113",
        history_as_of_issue="13",
        history_window=12,
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
    short_history = _history()[:8]
    with pytest.raises(ValueError, match="requires 12 prior official rows"):
        evaluate_deployment_gate(
            _payload(issue="26113", history_window=12), short_history
        )


def test_26103_replay_preserves_recorded_reduce_or_empty_state():
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
    assert result.history_window == 14
    assert result.break_even_to_median == pytest.approx(2.24, abs=0.01)
    assert "丢场式减注" in format_deployment_gate(result)
    assert "无合格减注版" in format_deployment_gate(result)


def test_26104_replay_passes_at_recorded_point_95_compromise():
    result = evaluate_deployment_gate(_payload(), _history())
    assert result.state is DeploymentGateState.PASS
    assert result.break_even_bonus == pytest.approx(6097)
    assert result.history_window == 14
    assert result.break_even_to_median == pytest.approx(0.95, abs=0.01)
    assert result.capital_utilization == pytest.approx(0.81)


def _write_cli_files(tmp_path, *, ratio: float):
    median = 1000.0
    gate_file = tmp_path / "gate.json"
    gate_file.write_text(json.dumps({
        "issue": "26113",
        "period_cap_yuan": 100,
        "history_as_of_issue": "26113",
        "history_window": 12,
        "candidates": [{
            "id": "candidate",
            "stake_yuan": 100,
            "hit_probability": 100 / (median * ratio),
        }],
    }), encoding="utf-8")
    history_file = tmp_path / "history.json"
    rows = []
    for offset in range(12):
        issue = str(26112 - offset)
        rows.append({
            "lotteryDrawNum": issue,
            "lotteryDrawTime": "2026-08-26",
            "lotteryDrawResult": "* * * * * * * * * * * * * *",
            "prizeLevelListRj": [{
                "stakeCount": "10",
                "stakeAmount": f"{median:.0f}",
            }],
            "totalSaleAmountRj": f"{median * 10 / 0.64:.0f}",
        })
    history_file.write_text(json.dumps({"value": {"list": rows}}), encoding="utf-8")
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


def test_cohort_accepts_floor_rounded_high_count_payout_26111():
    # 26111 实况：43,365 注 × ¥215 / 销量 ¥14,617,834 → 观察返奖率 63.78%。
    # 单注奖金向下取整到元在高中奖注数下把返奖率压出旧 ±0.2pp 平坦容差,
    # 但实付总额与 销量×64% 的差 (¥31,938.76) < 注数 (43,365×¥1),属合法取整损耗。
    history = _history() + [
        OfficialRenjiuHistory(
            issue="26111",
            draw_date="2026-08-28",
            stake_count=43365,
            stake_amount=215.0,
            sale_amount=14617834.0,
        )
    ]
    result = evaluate_deployment_gate(
        _payload(issue="26112", history_as_of_issue="26112", history_window=12),
        history,
    )
    assert "26111" in result.history_issues


def test_cohort_still_rejects_true_return_rate_drift():
    history = _history() + [
        OfficialRenjiuHistory(
            issue="26111",
            draw_date="2026-08-28",
            stake_count=43365,
            stake_amount=210.0,  # 少付超过取整损耗上限
            sale_amount=14617834.0,
        )
    ]
    with pytest.raises(ValueError, match="return rate drifted"):
        evaluate_deployment_gate(
            _payload(issue="26112", history_as_of_issue="26112", history_window=12),
            history,
        )


def test_gate_requires_twelve_from_effective_issue_and_preserves_legacy_replay():
    with pytest.raises(ValueError, match="must equal 12"):
        evaluate_deployment_gate(
            _payload(issue="26113", history_as_of_issue="26113", history_window=14),
            _history(),
        )

    legacy = evaluate_deployment_gate(_payload(history_window=14), _history())

    assert legacy.history_window == 14


def test_floor_rounding_rejects_overpayment_and_one_yuan_per_winner_shortfall():
    exact = OfficialRenjiuHistory("1", "2026-01-01", 10, 64.0, 1000.0)
    just_under_limit = OfficialRenjiuHistory(
        "1", "2026-01-01", 10, 63.00000001, 1000.0
    )
    over = OfficialRenjiuHistory("1", "2026-01-01", 10, 64.1, 1000.0)
    short = OfficialRenjiuHistory("1", "2026-01-01", 10, 63.0, 1000.0)
    assert exact.payout_consistent_with_return_rate()
    assert just_under_limit.payout_consistent_with_return_rate()
    assert not over.payout_consistent_with_return_rate()
    assert not short.payout_consistent_with_return_rate()


def test_deployment_selects_lowest_break_even_inside_cap():
    """s条修订(2026-08-31):固定奖金玩法按回本线最小选档,不按 P 最大。

    26114 实证:¥256→¥1,728 时 P 涨 4.1 倍而回本线从 ¥3,902 爬到 ¥6,417,
    当晚实开 ¥214——加注让经济性单调变差。
    """
    result = evaluate_deployment_gate(
        _payload(candidates=[
            {"id": "small", "stake_yuan": 288, "hit_probability": 0.14},
            {"id": "wide", "stake_yuan": 384, "hit_probability": 0.16},
        ]),
        _history(),
    )
    assert result.selected_id == "small"
    assert result.break_even_bonus == pytest.approx(288 / 0.14)


def test_deployment_and_optimizer_select_the_same_fixed_bonus_candidate():
    optimized = optimize({
        "issue": "26114",
        "price_per_note": 2,
        "budget_yuan": 10,
        "median_bonus_yuan": 1000,
        "fair": {
            "1": {"home": 0.50, "draw": 0.30, "away": 0.20},
            "2": {"home": 0.60, "draw": 0.25, "away": 0.15},
        },
        "versions": [
            {"id": "small", "faces": {"1": "3", "2": "3"}},
            {"id": "wide", "faces": {"1": "31", "2": "31"}},
        ],
    })
    history = [
        OfficialRenjiuHistory(str(26113 - offset), "", 64, 1000.0, 100000.0)
        for offset in range(12)
    ]

    deployed = evaluate_deployment_gate(
        {
            "issue": "26114",
            "history_as_of_issue": "26114",
            "period_cap_yuan": 10,
            "history_window": 12,
            "candidates": [
                {
                    "id": version["id"],
                    "stake_yuan": version["cost_yuan"],
                    "hit_probability": version["p_all"],
                }
                for version in optimized["versions"]
            ],
        },
        history,
    )

    assert deployed.selected_id == optimized["best_within_cap_id"] == "small"
