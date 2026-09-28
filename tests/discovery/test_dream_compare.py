from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.discovery.dream_compare import (
    compare_day,
    decision_rule_best,
    score_tickets,
    summarize,
)

BOOK = {
    "A": {"belief": {"3": 0.5, "1": 0.3, "0": 0.2}, "odds": {"3": 1.8, "1": 3.2, "0": 4.5}},
    "B": {"belief": {"3": 0.4, "1": 0.3, "0": 0.3}, "odds": {"3": 2.3, "1": 3.1, "0": 2.9}},
    "C": {"belief": {"3": 0.7, "1": 0.2, "0": 0.1}, "odds": {"3": 1.3, "1": 4.6, "0": 8.0}},
}
RESULTS = {"A": {"outcome_90": "3"}, "B": {"outcome_90": "1"}, "C": {"outcome_90": "3"}}


def test_decision_rule_best_is_max_p_among_combos_that_pay_back_on_a_hit():
    best = decision_rule_best(BOOK)
    assert best is not None and best["modal_return_per_yuan"] > 1
    assert 2 <= len(best["legs"]) <= 4 and best["notes"] <= 4
    assert all(set(leg["faces"]) <= {"3", "1", "0"} for leg in best["legs"])
    assert decision_rule_best({"A": BOOK["A"]}) is None


def test_score_tickets_handles_hit_miss_pending_and_void():
    hit = score_tickets(
        [[{"code": "A", "faces": "3"}, {"code": "B", "faces": "10"}]], BOOK, RESULTS
    )
    assert hit == {"status": "settled", "hit": True, "return_per_yuan": round(1.8 * 3.1 / 2, 4)}
    miss = score_tickets(
        [[{"code": "A", "faces": "0"}, {"code": "X", "faces": "3"}]], BOOK, RESULTS
    )
    assert miss == {"status": "settled", "hit": False, "return_per_yuan": 0.0}
    pending = score_tickets(
        [[{"code": "A", "faces": "3"}, {"code": "X", "faces": "3"}]], BOOK, RESULTS
    )
    assert pending == {"status": "pending"}
    void = score_tickets(
        [[{"code": "A", "faces": "3"}, {"code": "V", "faces": "0"}]],
        BOOK,
        {**RESULTS, "V": {"void": True}},
    )
    assert void["hit"] is True and void["return_per_yuan"] == round(1.8 / 1, 4)


def _report():
    return {
        "day": "2026-09-29",
        "status": "recorded",
        "world_id": "w",
        "manifest_hash": "m",
        "offer_book": BOOK,
        "decision_rule_best": {
            "legs": [{"code": "A", "faces": "3"}, {"code": "C", "faces": "3"}],
            "p_belief": 0.35,
            "notes": 1,
            "modal_return_per_yuan": 2.34,
        },
        "band_best": {
            "10x": {
                "tickets": [[{"code": "A", "faces": "3"}, {"code": "B", "faces": "0"}]],
                "p_belief": "0.06",
                "combined_odds": "5.22",
                "stake_minor": 200,
            }
        },
        "ticket_snapshot": {"betslips": [{"slip_id": "S1"}]},
    }


def test_compare_day_scores_four_row_kinds():
    slip = BetSlip(
        slip_id="S1", channel="jczq", placed_at="2026-09-29", multiplier=10, combo_sizes=(2,),
        legs=[SlipLeg(key="A", market="had", selections=("home",), odds=(1.8,)),
              SlipLeg(key="C", market="had", selections=("home",), odds=(1.3,))],
    )
    late = BetSlip(
        slip_id="S2", channel="jczq", placed_at="2026-09-29", combo_sizes=(2,),
        legs=[SlipLeg(key="B", market="hhad", line=-1.0, selections=("away",), odds=(1.5,)),
              SlipLeg(key="C", market="had", selections=("home",), odds=(1.3,))],
    )
    out = compare_day(_report(), RESULTS, [slip, late])
    rows = {(r["kind"], r.get("id")): r for r in out["rows"]}
    s1 = rows[("actual", "S1")]
    assert s1["in_world"] and s1["frozen_at_cutoff"] and abs(s1["p_belief"] - 0.35) < 1e-9
    assert s1["hit"] is True and s1["pnl_per_yuan"] == round(1.8 * 1.3 - 1, 4)
    s2 = rows[("actual", "S2")]
    assert s2["in_world"] is False and s2["p_belief"] is None and s2["frozen_at_cutoff"] is False
    assert rows[("decision_rule", None)]["hit"] is True
    assert rows[("band", "10x")]["hit"] is False and rows[("band", "10x")]["pnl_per_yuan"] == -1.0
    assert rows[("empty", None)]["pnl_per_yuan"] == 0.0


def test_summarize_reports_means_and_withholds_ci_below_twenty_days():
    days = [
        {
            "day": f"d{i}",
            "rows": [
                {"kind": "actual", "status": "settled", "stake_yuan": 20, "pnl_yuan": -20.0,
                 "pnl_per_yuan": -1.0, "p_belief": 0.3, "hit": False},
                {"kind": "decision_rule", "status": "settled", "pnl_per_yuan": 0.5,
                 "p_belief": 0.4, "hit": True},
                {"kind": "empty", "status": "settled", "pnl_per_yuan": 0.0},
            ],
        }
        for i in range(3)
    ]
    summary = summarize(days)
    assert summary["n_days"] == 3
    assert summary["kinds"]["decision_rule"]["hit_rate"] == 1.0
    assert summary["actual_minus_rule"]["mean"] == -1.5
    assert summary["actual_minus_rule"]["ci95"] is None
    many = summarize(days * 7)
    assert many["actual_minus_rule"]["ci95"] == [-1.5, -1.5]
