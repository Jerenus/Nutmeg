import json

from nutmeg.decision.jczq_reads import build_jczq_reads, intake_board

RESEARCH = {
    "name": "A-B",
    "summary": "s",
    "confidence": 3,
    "anchor_integrity": "pass",
    "anchor_side": "home",
    "license_questions": {
        "q1_spine": True,
        "q2_route": True,
        "q3a_opponent_scores": False,
        "q3b_opponent_takes_points": False,
        "q4_no_context_flag": True,
    },
    "death_three_proofs": {
        "away": {
            "a_no_scoring_mechanism": True,
            "b_precedent_carrier_gone": True,
            "c_anchor_pass": True,
            "proof_count": "3/3",
            "verdict": "dead",
            "detail": "three independent proofs",
        }
    },
    "directional_flags": [],
    "nondirectional_flags": [],
    "crash_markers": [],
    "precedents": [],
}


def _day(tmp_path):
    day_dir = tmp_path / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    legs = {
        "周五001": {
            "match_id": "m-1",
            "name": "A-B",
            "competition": "x",
            "kickoff_bj": "2026-09-20T03:00:00+08:00",
            "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
            "hhad_line": None,
            "judgment_tier": "deep_research",
            "faces": "310",
        }
    }
    (day_dir / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-19", "legs": legs}), encoding="utf-8"
    )
    (day_dir / "research-周五001.json").write_text(
        json.dumps(RESEARCH, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def test_intake_backfills_labels_and_face_status_by_code(tmp_path):
    root = _day(tmp_path)

    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)

    legs = json.loads(
        (root / "daily" / "2026-09-19" / "jczq-legs-base.json").read_text(
            encoding="utf-8"
        )
    )["legs"]
    leg = legs["周五001"]
    assert report["ok"] == ["周五001"]
    assert leg["confidence"] == 3
    assert leg["anchor_integrity"] == "pass"
    assert leg["face_status"]["away"]["state"] == "dead"
    assert leg["faces"] == "31"


def test_build_reads_marks_ai_judge_and_deep_tier(tmp_path):
    root = _day(tmp_path)
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    reads = build_jczq_reads(
        day="2026-09-19",
        jczq_dir=root,
        made_at="2026-09-19T12:00:00+08:00",
    )

    assert len(reads) == 1
    assert reads[0]["judge"] == "ai:jczq-analyst"
    assert reads[0]["status"] == "draft"
    assert reads[0]["match_id"] == "m-1"
    assert reads[0]["judgment_tier"] == "deep_research"
    assert abs(sum(reads[0]["belief"].values()) - 1) < 1e-9
    assert reads[0]["belief"]["away"] == 0.0


def test_write_quarantines_intake_errors_and_restores_price_only(tmp_path):
    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    invalid = {**RESEARCH, "crash_markers": ["叙述误入标签位" * 20]}
    research_path = day_dir / "research-周五001.json"
    research_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    run_report_path = day_dir / "research-run-2026-09-19.json"
    run_report_path.write_text(
        json.dumps(
            {"day": "2026-09-19", "matches": [{"code": "周五001", "status": "done"}]}
        ),
        encoding="utf-8",
    )

    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)

    assert "周五001" in report["failed"]
    board = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))
    assert board["legs"]["周五001"]["judgment_tier"] == "price_only"
    assert not research_path.exists()
    rejected = json.loads(
        (day_dir / "research-周五001.rejected.json").read_text(encoding="utf-8")
    )
    assert rejected["research"]["crash_markers"] == invalid["crash_markers"]
    run_report = json.loads(run_report_path.read_text(encoding="utf-8"))
    assert run_report["matches"][0]["status"] == "rejected"
