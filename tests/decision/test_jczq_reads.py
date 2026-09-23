import json

from nutmeg.decision.jczq_reads import build_jczq_reads, intake_board

STANCE = {
    "face": "3",
    "structure": "double",
    "cover": "1",
    "confidence": 3,
    "falsifier": "客队首发若有主力门将则本判断作废",
    "why_not_market": "structure",
    "tilt": None,
    "alt_face": "1",
    "market_read": "agree",
}

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
    "stance": STANCE,
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
    assert leg["face_status"]["away"]["basis"] == "researched"
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


def test_every_board_match_gets_a_read_even_without_research(tmp_path):
    root = _day(tmp_path)
    board_path = root / "daily" / "2026-09-19" / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    for index in (2, 3):
        board["legs"][f"周五00{index}"] = {
            "match_id": f"m-{index}",
            "name": f"T{index}A-T{index}B",
            "competition": "x",
            "kickoff_bj": "2026-09-20T04:00:00+08:00",
            "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "hhad_line": None,
            "judgment_tier": "price_only",
            "faces": "310",
        }
    board_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    reads = build_jczq_reads(
        day="2026-09-19",
        jczq_dir=root,
        made_at="2026-09-19T12:00:00+08:00",
    )

    assert len(reads) == 3
    researched = [read for read in reads if read["judge"] == "ai:jczq-analyst"]
    anchored = [read for read in reads if read["judge"] == "market-anchor"]
    assert len(researched) == 1 and len(anchored) == 2
    assert all(read["status"] == "draft" for read in reads)
    anchor = anchored[0]
    assert anchor["belief"] == anchor["prior"]
    assert anchor["confidence"] == 1
    assert anchor["judgment_tier"] == "price_only"


def test_researched_basis_wins_over_a_stale_price_only_tier(tmp_path):
    root = _day(tmp_path)
    board_path = root / "daily" / "2026-09-19" / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["legs"]["周五001"]["judgment_tier"] = "price_only"
    board_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    [read] = build_jczq_reads(
        day="2026-09-19",
        jczq_dir=root,
        made_at="2026-09-19T12:00:00+08:00",
    )

    assert read["judge"] == "ai:jczq-analyst"
    assert read["judgment_tier"] == "deep_research"


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


def test_intake_writes_stance_and_derived_faces(tmp_path):
    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    research = {**RESEARCH, "stance": STANCE}
    (day_dir / "research-周五001.json").write_text(
        json.dumps(research, ensure_ascii=False), encoding="utf-8"
    )

    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)

    assert report["ok"] == ["周五001"]
    leg = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))[
        "legs"
    ]["周五001"]
    assert leg["stance"]["faces"] == "31"
    assert leg["faces"] == "31"


def test_intake_rejects_stance_covering_a_dead_face(tmp_path):
    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    research = {**RESEARCH, "stance": {**STANCE, "cover": "0"}}  # away 已判死
    (day_dir / "research-周五001.json").write_text(
        json.dumps(research, ensure_ascii=False), encoding="utf-8"
    )

    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)

    assert "周五001" in report["failed"]
    assert any("已判死" in message for message in report["failed"]["周五001"])
    board = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))
    assert board["legs"]["周五001"]["judgment_tier"] == "price_only"
    assert "face_status" not in board["legs"]["周五001"]
    assert not (day_dir / "research-周五001.json").exists()
    assert (day_dir / "research-周五001.rejected.json").exists()


def test_intake_without_stance_is_rejected(tmp_path):
    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    research = {key: value for key, value in RESEARCH.items() if key != "stance"}
    (day_dir / "research-周五001.json").write_text(
        json.dumps(research, ensure_ascii=False), encoding="utf-8"
    )

    report = intake_board(day="2026-09-19", jczq_dir=root, write=False)

    assert any("stance" in message for message in report["failed"].get("周五001", []))
    assert (day_dir / "research-周五001.json").exists()


def test_reads_take_belief_from_tilt_and_carry_stance(tmp_path):
    root = _day(tmp_path)
    tilt = {
        "face": "3",
        "expires_if": "X 出场则撤回",
        "evidence": [
            {
                "tier": "official",
                "kind": "absence_official",
                "pp": 6,
                "source": "club",
                "captured_at": "2026-09-19T10:00:00+08:00",
            }
        ],
    }
    research = {
        **RESEARCH,
        "stance": {**STANCE, "why_not_market": "tilt_evidence", "tilt": tilt},
    }
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(
        json.dumps(research, ensure_ascii=False), encoding="utf-8"
    )
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    reads = build_jczq_reads(
        day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00"
    )

    r = reads[0]
    # 拨动 +6pp 作用在 prior 上（home 0.60→0.66，其余按比例缩：draw 0.2125 / away 0.1275），
    # 再把三证判死的 away 清零并在活面上归一：home 0.66/0.8725 = 0.756。
    assert round(r["belief"]["home"], 3) == 0.756
    assert r["belief"]["away"] == 0.0
    assert abs(sum(r["belief"].values()) - 1) < 1e-9
    assert r["adjustment_evidence_tiers"] == ["official"]
    assert r["falsifier"] == STANCE["falsifier"] and r["confidence"] == 3
    assert r["commitment_tier"] == "lean" and r["stance"]["faces"] == "31"
    assert r["stance"]["tilt_applied_pp"] == 6 and r["stance"]["tilt_zeroed"] is False


def test_reads_zero_small_tilt_and_keep_alive_normalisation(tmp_path):
    root = _day(tmp_path)
    tilt = {
        "face": "3",
        "expires_if": "",
        "evidence": [
            {
                "tier": "inferred",
                "kind": "rotation_confirmed",
                "pp": 2,
                "source": "s",
                "captured_at": "2026-09-19T10:00:00+08:00",
            }
        ],
    }
    research = {
        **RESEARCH,
        "stance": {**STANCE, "why_not_market": "tilt_evidence", "tilt": tilt},
    }
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(
        json.dumps(research, ensure_ascii=False), encoding="utf-8"
    )
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    r = build_jczq_reads(
        day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00"
    )[0]

    assert r["belief"]["away"] == 0.0  # away 判死 → 活面归一仍生效
    assert r["stance"]["tilt_zeroed"] is True and "归零" in r["stance"]["tilt_reason"]
    assert r["adjustment_evidence_tiers"] == []
