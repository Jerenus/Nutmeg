import json

import pytest

from nutmeg.decision.plan_flow import run_choose, run_frontier, run_tiers
from nutmeg.decision.workbench import read_events

LQ4 = {
    "q1_spine": True,
    "q2_route": True,
    "q3a_opponent_scores": False,
    "q4_no_context_flag": True,
}


def _data_dir(tmp_path):
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    (tmp_path / "jczq").mkdir()
    legs = {
        str(i): {
            "name": f"m{i}",
            "license_questions": LQ4,
            "anchor_integrity": "pass",
            "crash_markers": [],
            "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
            "_d3": {"away": {"a": True, "b": True, "c": False}},
            "face_status": {
                face: {
                    "state": "alive" if face == "home" else "dead",
                    "proofs": {},
                    "precedent": "none",
                    "source": "x",
                }
                for face in ("home", "draw", "away")
            },
        }
        for i in range(1, 15)
    }
    (zucai / "26130-legs-base.json").write_text(
        json.dumps({"issue": "26130", "legs": legs}), encoding="utf-8"
    )
    (zucai / "26130-issue.json").write_text(
        json.dumps(
            {
                "issue_id": "26130",
                "matches": [
                    {"match_no": i, "kickoff_bj": "2026-09-26 02:00"}
                    for i in range(1, 15)
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_tiers_writes_file_and_root_candidate_node(tmp_path):
    data_dir = _data_dir(tmp_path)
    out = run_tiers(issue="26130", data_dir=data_dir)
    doc = json.loads((data_dir / "zucai" / "26130-tiers.json").read_text("utf-8"))
    assert doc["tiers"]["1"] == "T1"
    assert doc["wind"]["regime"] in ("hot", "mixed", "cold", "coin")
    events = read_events(data_dir / "jczq", "2026-09-26")
    assert events[-1]["kind"] == "candidate"
    assert events[-1]["payload"]["version"].startswith("tiers@")
    assert out["tiers_hash"] == events[-1]["payload"]["version"].split("@")[1]


def test_frontier_writes_points_as_children_of_tiers_root(tmp_path):
    data_dir = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=data_dir)
    frontier = run_frontier(
        issue="26130", channel="renjiu", cap_yuan=400, data_dir=data_dir
    )
    doc = json.loads(
        (data_dir / "zucai" / "26130-frontier-renjiu.json").read_text("utf-8")
    )
    assert doc["max_p"] == frontier["max_p"] and doc["strict_max_p"] is not None
    events = [
        event
        for event in read_events(data_dir / "jczq", "2026-09-26")
        if event["kind"] == "candidate"
    ]
    children = [
        event for event in events if event["payload"]["version"].startswith("frontier#")
    ]
    assert children
    assert all(event["payload"]["parent_version"].startswith("tiers@") for event in children)
    assert all(event["payload"]["verdict"] == "considered" for event in children)


def test_choose_writes_legs_file_and_hangs_node_under_the_point(tmp_path):
    data_dir = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=data_dir)
    run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=data_dir)
    result = run_choose(issue="26130", channel="renjiu", point=0, data_dir=data_dir)
    legs = json.loads(
        (data_dir / "zucai" / "26130-legs-renjiu.json").read_text("utf-8")
    )
    assert len(legs["legs"]) == 9 and result["candidate_node"] == "chosen#0@renjiu"
    event = read_events(data_dir / "jczq", "2026-09-26")[-1]
    assert event["payload"]["parent_version"] == "frontier#0@¥400"
    assert event["payload"]["verdict"] == "chosen"


def test_choose_with_edit_hangs_under_the_point_and_records_the_edit(tmp_path):
    data_dir = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=data_dir)
    run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=data_dir)
    edit = data_dir / "edit.json"
    edit.write_text(
        json.dumps(
            {
                "1": "3",
                "2": "3",
                "3": "3",
                "4": "3",
                "5": "3",
                "6": "3",
                "7": "3",
                "8": "3",
                "9": "3",
            }
        ),
        encoding="utf-8",
    )
    result = run_choose(
        issue="26130", channel="renjiu", point=0, edit_file=edit, data_dir=data_dir
    )
    event = read_events(data_dir / "jczq", "2026-09-26")[-1]
    assert event["payload"]["parent_version"] == "frontier#0@¥400"
    assert event["payload"]["version"] == "edit#1@renjiu"
    assert result["candidate_node"] == "edit#1@renjiu"


def test_frontier_refuses_without_tiers(tmp_path):
    data_dir = _data_dir(tmp_path)
    with pytest.raises(FileNotFoundError, match="tiers"):
        run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=data_dir)
