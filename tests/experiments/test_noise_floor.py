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
