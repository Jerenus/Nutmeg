from __future__ import annotations

import importlib.util
import json
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


def test_research_labels_does_not_admit_legacy_free_text_unit_as_controlled():
    labels = corpus_build._research_labels(
        {
            "hole_location": {
                "unit": "defensive_spine_plus_midfield_pivot",
                "names": ["legacy player"],
                "priced": "partly priced",
            }
        }
    )

    assert labels["hole_location_unit"] is None
    assert labels["hole_location_side"] is None
    assert labels["hole_location_priced_in"] is None


def test_postmortem_labels_are_merged_as_fifth_source():
    labels = {"anchor_integrity": "pass"}
    postmortem = {
        "actual_was_excluded": True,
        "actual_face_prior": {
            "fair_pp": 20.0,
            "exclusion_tier": "灰带",
            "death_proof_count": "2/3",
            "precedent_status": "dead",
        },
    }

    assert corpus_build._merge_postmortem(labels, postmortem) == {
        "anchor_integrity": "pass",
        "postmortem": postmortem,
    }


def test_jczq_rows_loads_postmortem_as_fifth_source(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    day_dir = root / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (root / "jc-results.json").write_text(
        json.dumps({"2026-09-19": {"周六001": {"ft_home": 1, "ft_away": 0}}}),
        encoding="utf-8",
    )
    (day_dir / "bold_odds.json").write_text(
        json.dumps(
            {
                "周六001": {
                    "match_winner": {"fair_probability": {"home": 0.5, "draw": 0.3, "away": 0.2}}
                }
            }
        ),
        encoding="utf-8",
    )
    postmortem = {"actual_was_excluded": True, "actual_face_prior": {"fair_pp": 50.0}}
    (day_dir / "postmortem-周六001.json").write_text(json.dumps(postmortem), encoding="utf-8")
    monkeypatch.setattr(corpus_build, "J", str(root))

    rows = corpus_build.jczq_rows()

    assert rows[0]["labels"]["postmortem"] == postmortem


def test_jczq_rows_marks_research_captured_before_kickoff_as_provable(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    day_dir = root / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (root / "jc-results.json").write_text(
        json.dumps({"2026-09-19": {"周六001": {"ft_home": 1, "ft_away": 0}}}),
        encoding="utf-8",
    )
    (day_dir / "bold_odds.json").write_text(
        json.dumps(
            {
                "周六001": {
                    "match_winner": {"fair_probability": {"home": 0.5, "draw": 0.3, "away": 0.2}}
                }
            }
        ),
        encoding="utf-8",
    )
    (day_dir / "jczq-legs-base.json").write_text(
        json.dumps({"legs": {"周六001": {"kickoff_bj": "2026-09-19T20:00:00+08:00"}}}),
        encoding="utf-8",
    )
    (day_dir / "research-周六001.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-09-19T19:59:00+08:00",
                "anchor_integrity": "pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_build, "J", str(root))

    row = corpus_build.jczq_rows()[0]

    assert row["provably_prospective"] is True
    assert row["judged_at_source"] == "research.captured_at"


def test_prospective_fields_exposes_leak_and_keeps_missing_time_unknown():
    leaked = corpus_build._prospective_fields(
        judged_at="2026-09-19T20:00:00+08:00",
        kickoff_bj="2026-09-19T20:00:00+08:00",
        judged_at_source="legs-base.legs[n].judged_at",
    )
    unknown = corpus_build._prospective_fields(
        judged_at=None,
        kickoff_bj="2026-09-19T20:00:00+08:00",
        judged_at_source=None,
    )

    assert leaked == {
        "provably_prospective": False,
        "judged_at_source": "legs-base.legs[n].judged_at",
    }
    assert unknown == {"provably_prospective": None, "judged_at_source": None}
