from __future__ import annotations

import json

from typer.testing import CliRunner

from nutmeg.decision.postmortem import postmortem_rows
from nutmeg.interfaces.cli import app


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _jczq_day(tmp_path):
    data = tmp_path / "data"
    day_dir = data / "jczq" / "daily" / "2026-09-19"
    _write(
        day_dir / "jczq-legs-base.json",
        {
            "day": "2026-09-19",
            "legs": {
                "周六001": {
                    "match_id": "match-1",
                    "faces": "31",
                    "fair": {"home": 0.55, "draw": 0.25, "away": 0.20},
                },
                "周六002": {
                    "match_id": "match-2",
                    "faces": "3",
                    "fair": {"home": 0.60, "draw": 0.24, "away": 0.16},
                },
            },
        },
    )
    _write(
        day_dir / "research-周六001.json",
        {
            "anchor_integrity": "pass",
            "confidence": 4,
            "directional_flags": [["anchor_shield_out", "1"]],
            "nondirectional_flags": ["two_way_instability"],
            "hole_location": {"unit": "attack"},
            "death_three_proofs": {
                "away": {"proof_count": "2/3", "verdict": "alive"}
            },
            "precedents": [["0", "same shape", "dead"]],
        },
    )
    _write(
        data / "jczq" / "jc-results.json",
        {
            "2026-09-19": {
                "周六001": {"match_id": "100", "ft_home": 0, "ft_away": 1}
            }
        },
    )
    return data


def test_jczq_postmortem_keeps_actual_prior_without_inventing_a_call(tmp_path):
    rows = postmortem_rows(day="2026-09-19", issue=None, data_dir=_jczq_day(tmp_path))

    assert len(rows) == 1
    row = rows[0]
    assert row["match_id"] == "match-1"
    assert row["actual"] == "0"
    assert row["call_kind"] == "none"
    assert row["called_faces"] is None
    assert row["hit"] is None
    assert row["excluded_faces"] == []
    assert row["actual_was_excluded"] is None
    assert row["actual_face_prior"] == {
        "fair_pp": 20.0,
        "exclusion_tier": "灰带",
        "death_proof_count": "2/3",
        "precedent_status": "dead",
    }
    assert row["hole_location_unit"] == "attack"
    assert row["source"] == "research"
    assert row["computed_at"].endswith("+08:00")


def test_postmortem_cli_writes_settled_rows_and_reports_pending(tmp_path):
    data = _jczq_day(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "decision-postmortem",
            "--day",
            "2026-09-19",
            "--data-dir",
            str(data),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "written=1 pending=1" in result.output
    artifact = data / "jczq" / "daily" / "2026-09-19" / "postmortem-周六001.json"
    assert json.loads(artifact.read_text(encoding="utf-8"))["actual"] == "0"


def test_missing_call_keeps_call_null_but_still_derives_actual_face_prior(tmp_path):
    data = _jczq_day(tmp_path)
    results_path = data / "jczq" / "jc-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["2026-09-19"]["周六002"] = {
        "match_id": "200",
        "ft_home": 2,
        "ft_away": 2,
    }
    results_path.write_text(json.dumps(results), encoding="utf-8")
    board_path = data / "jczq" / "daily" / "2026-09-19" / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    del board["legs"]["周六002"]["faces"]
    board_path.write_text(json.dumps(board), encoding="utf-8")

    row = postmortem_rows(day="2026-09-19", issue=None, data_dir=data)[1]

    assert row["call_kind"] == "none"
    assert row["actual_was_excluded"] is None
    assert row["actual_face_prior"]["exclusion_tier"] == "买方差"


def test_zucai_postmortem_uses_calls_fair_and_official_results(tmp_path):
    data = tmp_path / "data"
    z = data / "zucai"
    _write(z / "official-results.json", {"26129": "0 3"})
    _write(z / "26129-calls.json", {"1": {"kind": "single", "faces": "3"}})
    _write(z / "26129-fair.json", {"1": {"home": 0.52, "draw": 0.28, "away": 0.20}})
    _write(
        z / "26129-legs-base.json",
        {
            "legs": {
                "1": {
                    "match_id": "zc-1",
                    "anchor_integrity": "fail",
                    "confidence": 3,
                    "face_status": {
                        "away": {
                            "proofs": {"a": True, "b": True, "c": False},
                            "precedent": "alive",
                        }
                    },
                }
            }
        },
    )

    rows = postmortem_rows(day="2026-09-19", issue="26129", data_dir=data)

    assert len(rows) == 1
    assert rows[0]["issue"] == "26129"
    assert rows[0]["match_no"] == 1
    assert rows[0]["actual_was_excluded"] is True
    assert rows[0]["actual_face_prior"]["death_proof_count"] == "2/3"
    assert rows[0]["actual_face_prior"]["precedent_status"] == "alive"
