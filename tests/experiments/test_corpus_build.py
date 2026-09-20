from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "experiments" / "corpus_build.py"
_SPEC = importlib.util.spec_from_file_location("corpus_build", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
corpus_build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(corpus_build)


def test_research_labels_flattens_controlled_hole_location():
    labels = corpus_build._research_labels(
        {
            "hole_location": {
                "unit": "attack",
                "side": "away",
                "priced_in": False,
                "detail": "客队中锋缺阵",
            }
        }
    )

    assert labels["hole_location_unit"] == "attack"
    assert labels["hole_location_side"] == "away"
    assert labels["hole_location_priced_in"] is False


def test_research_labels_does_not_guess_legacy_hole_location():
    labels = corpus_build._research_labels(
        {"hole_location": {"anchor": "attack", "opponent": "defense"}}
    )

    assert labels["hole_location_unit"] is None
    assert labels["hole_location_side"] is None
    assert labels["hole_location_priced_in"] is None
