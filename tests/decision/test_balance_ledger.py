import json
from pathlib import Path

from nutmeg.decision.balance_ledger import balance_ledger, balance_row


def _read(*, match_id="m1", belief=None):
    prior = {"home": 0.4, "draw": 0.3, "away": 0.3}
    return {
        "read_id": f"read-{match_id}",
        "match_id": match_id,
        "prior": prior,
        "belief": belief or dict(prior),
    }


def test_equal_belief_and_prior_never_moves_the_balance():
    ledger = balance_ledger([_read(match_id="m1"), _read(match_id="m2")])

    assert ledger["n_matches"] == 2
    assert ledger["n_moved"] == 0
    assert ledger["moved_pct"] == 0.0
    assert ledger["max_shift_pp"] == 0.0
    assert balance_row(_read())["moved_face"] is None


def test_shift_toward_the_actual_face_is_right_and_beats_market():
    read = _read(belief={"home": 0.46, "draw": 0.27, "away": 0.27})

    ledger = balance_ledger([read], outcomes={"m1": "home"})

    assert ledger["direction_right_n"] == 1
    assert ledger["direction_wrong_n"] == 0
    assert ledger["brier_vs_market_moved"] < 0
    assert balance_row(read)["shift_pp"] == 6.0
    assert balance_row(read)["moved_face"] == "home"


def test_shift_away_from_the_actual_face_is_wrong_and_loses_to_market():
    read = _read(belief={"home": 0.46, "draw": 0.27, "away": 0.27})

    ledger = balance_ledger([read], outcomes={"m1": "away"})

    assert ledger["direction_right_n"] == 0
    assert ledger["direction_wrong_n"] == 1
    assert ledger["brier_vs_market_moved"] > 0


def test_unsettled_ledger_keeps_outcome_metrics_unknown():
    ledger = balance_ledger(
        [_read(belief={"home": 0.46, "draw": 0.27, "away": 0.27})],
        outcomes=None,
    )

    assert ledger["brier_vs_market_moved"] is None
    assert ledger["brier_vs_market_all"] is None
    assert ledger["direction_right_n"] is None
    assert ledger["direction_wrong_n"] is None


def test_ledger_hash_changes_when_outcomes_arrive():
    read = _read(belief={"home": 0.46, "draw": 0.27, "away": 0.27})

    before = balance_ledger([read], outcomes=None)
    after = balance_ledger([read], outcomes={"m1": "home"})

    assert before != after


def test_real_26129_reads_have_zero_moves():
    path = Path(".nutmeg-data/zucai/26129-reads.json")
    reads = json.loads(path.read_text(encoding="utf-8"))

    ledger = balance_ledger(reads)

    assert ledger["n_matches"] == 14
    assert ledger["n_moved"] == 0
