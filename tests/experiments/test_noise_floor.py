import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[2] / "experiments" / "noise_floor.py"
_SPEC = importlib.util.spec_from_file_location("noise_floor", _PATH)
assert _SPEC and _SPEC.loader
noise_floor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(noise_floor)


def test_permutation_floor_is_deterministic_and_reports_seed():
    rows = [
        *({"factor": 0, "face_hit": 0, "fair": 0.25} for _ in range(5)),
        *({"factor": 1, "face_hit": 1, "fair": 0.25} for _ in range(5)),
    ]

    first = noise_floor.permutation_floor(
        rows, "factor", "face_hit_rate_resid_pp", n_perm=100, seed=20260920
    )
    second = noise_floor.permutation_floor(
        rows, "factor", "face_hit_rate_resid_pp", n_perm=100, seed=20260920
    )

    assert first == second
    assert first["n"] == 10
    assert first["observed_pp"] == 100.0
    assert first["seed"] == 20260920
    assert first["n_perm"] == 100
    assert first["verdict"] == "above_floor"


def test_permutation_floor_supports_continuous_factor_values():
    rows = [
        {"proofs": 0, "face_hit": 0, "fair": 0.2},
        {"proofs": 1, "face_hit": 0, "fair": 0.2},
        {"proofs": 2, "face_hit": 1, "fair": 0.2},
    ]

    result = noise_floor.permutation_floor(
        rows, "proofs", "face_hit_rate_resid_pp", n_perm=20, seed=7
    )

    assert result["n"] == 3
    assert result["observed_pp"] == 50.0


def test_permutation_floor_rejects_factor_without_variation():
    rows = [
        {"factor": 1, "face_hit": 0, "fair": 0.2},
        {"factor": 1, "face_hit": 1, "fair": 0.2},
    ]

    with pytest.raises(ValueError, match="至少两个不同取值"):
        noise_floor.permutation_floor(rows, "factor", "face_hit_rate_resid_pp", n_perm=10, seed=1)


def _c7_corpus_rows():
    base = {
        "actual": "3",
        "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
    }
    return [
        {
            **base,
            "provably_prospective": True,
            "labels": {"precedents": [["3", "alive"]]},
        },
        {
            **base,
            "actual": "0",
            "provably_prospective": True,
            "labels": {"precedents": [["3", "dead"]]},
        },
        {
            **base,
            "provably_prospective": None,
            "labels": {"precedents": [["3", "dead"]]},
        },
    ]


def test_analysis_defaults_to_provable_rows_and_always_reports_composition():
    result = noise_floor.analyze(
        _c7_corpus_rows(),
        factor="c7_live_precedent",
        include_unproven=False,
        n_perm=10,
        seed=1,
    )

    assert result["n"] == 2
    assert result["provable_n"] == 2
    assert result["unproven_n"] == 0


def test_analysis_include_unproven_reports_both_sample_components():
    result = noise_floor.analyze(
        _c7_corpus_rows(),
        factor="c7_live_precedent",
        include_unproven=True,
        n_perm=10,
        seed=1,
    )

    assert result["n"] == 3
    assert result["provable_n"] == 2
    assert result["unproven_n"] == 1


def test_cli_accepts_include_unproven_and_prints_counts(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps({"rows": _c7_corpus_rows()}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "noise_floor.py",
            "--factor",
            "c7_live_precedent",
            "--corpus",
            str(corpus),
            "--n-perm",
            "10",
            "--include-unproven",
        ],
    )

    noise_floor.main()

    result = json.loads(capsys.readouterr().out)
    assert result["provable_n"] == 2
    assert result["unproven_n"] == 1


def _labelled(actual, fair, **labels):
    return {"actual": actual, "fair": fair, "labels": labels, "provably_prospective": True}


def test_row_flags_merge_legs_judgment_and_plain_lists_and_filter_lexicon():
    row = _labelled(
        "3",
        {"home": 0.5, "draw": 0.3, "away": 0.2},
        directional_flags=["anchor_shield_out", "made_up_flag"],
        nondirectional_flags=[],
        judgment={
            "flags": ["venue_anomaly", "opening_new_coach_debut"],
            "directional_flags": [["self_made_tail", "0"]],
        },
    )
    flags = noise_floor.row_flags(row)
    assert flags["directional"] == {"anchor_shield_out", "self_made_tail"}
    assert flags["nondirectional"] == {"venue_anomaly"}
    assert flags["crash"] == {"opening_new_coach_debut"}


def test_flag_factors_admit_only_labelled_rows_and_target_the_right_face():
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    rows = [
        _labelled("0", fair, directional_flags=["weak_home_draw_trap"]),  # non-modal opened
        _labelled("3", fair, directional_flags=[]),
        {"actual": "1", "fair": fair, "labels": None},  # unlabelled → excluded
        _labelled("0", fair, nondirectional_flags=["two_way_instability"]),  # third face opened
        _labelled("1", fair, crash_markers=["opening_promoted_vs_paper"]),  # modal missed
    ]
    directional = noise_floor._directional_flag_rows(rows)
    assert [r["factor"] for r in directional] == [1, 0, 0, 0]
    assert directional[0]["face_hit"] == 1 and directional[0]["fair"] == 0.5  # 1 - modal
    third = noise_floor._nondirectional_flag_rows(rows)
    assert [r["factor"] for r in third] == [0, 0, 1, 0]
    assert third[2]["face_hit"] == 1 and third[2]["fair"] == 0.2
    crash = noise_floor._crash_marker_rows(rows)
    assert [r["factor"] for r in crash] == [0, 0, 0, 1]
    assert crash[3]["face_hit"] == 0 and crash[3]["fair"] == 0.5


def test_price_band_factors_admit_unlabelled_rows_and_use_audit_thresholds():
    rows = [
        {"actual": "3", "fair": {"home": 0.45, "draw": 0.38, "away": 0.17}},  # gap 7pp → C11
        {"actual": "1", "fair": {"home": 0.40, "draw": 0.30, "away": 0.30}},  # draw 30% → C12
        {"actual": "3", "fair": {"home": 0.60, "draw": 0.25, "away": 0.15}},  # neither
    ]
    c11 = noise_floor._false_direction_rows(rows)
    assert [r["factor"] for r in c11] == [1, 0, 0] and c11[0]["fair"] == 0.45
    c12 = noise_floor._draw_band_rows(rows)
    assert [r["factor"] for r in c12] == [0, 1, 0] and c12[1]["face_hit"] == 1


def test_conf_and_belief_offset_factors():
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    rows = [
        {"actual": "3", "fair": fair, "conf": 4},
        {"actual": "0", "fair": fair, "conf": None},
        {"actual": "0", "fair": fair, "belief": {"home": 0.4, "draw": 0.3, "away": 0.3},
         "belief_moved": True},
        {"actual": "3", "fair": fair, "belief": fair, "belief_moved": False},
    ]
    conf = noise_floor._conf_rows(rows)
    assert [r["factor"] for r in conf] == [4.0]
    offset = noise_floor._belief_offset_rows(rows)
    assert len(offset) == 1 and offset[0]["factor"] == 0  # belief modal still home, offset -10pp
    assert offset[0]["fair"] == 0.5 and offset[0]["face_hit"] == 0


def test_analyze_reports_insufficient_instead_of_raising(tmp_path):
    rows = [
        {
            "actual": "3",
            "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "belief": {"home": 0.6, "draw": 0.25, "away": 0.15},
            "belief_moved": True,
            "provably_prospective": True,
        }
    ]
    result = noise_floor.analyze(rows, factor="belief_offset_anchor", n_perm=10)
    assert result["verdict"] == "insufficient"
    assert result["n"] == 1 and result["observed_pp"] is None
