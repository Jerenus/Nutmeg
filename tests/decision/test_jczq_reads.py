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
    invalid = {**RESEARCH, "crash_markers": [["嵌套", "误入标签位"]]}
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


def test_reads_express_small_tilt_and_keep_alive_normalisation(tmp_path):
    root = _day(tmp_path)
    tilt = {
        "face": "3",
        "expires_if": "",
        "evidence": [
            {
                # 2026-09-30：拨动须含官宣/确证结构级锚，否则归零
                "tier": "confirmed_structural",
                "kind": "rotation_confirmed",
                "pp": 3,
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
    # strength-v2（2026-09-26）：2pp 的推断级偏移如实表达，不再归零
    assert r["stance"]["tilt_zeroed"] is False and r["stance"]["tilt_applied_pp"] == 3
    assert r["adjustment_evidence_tiers"] == ["confirmed_structural"]


def test_rebuild_keeps_the_read_of_a_match_that_already_kicked_off(tmp_path):
    """开球后重建不许改写该场的 Read（赛后价格会混进语料/F9，2026-09-26 17:15 刷新后）。"""
    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    [before] = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                                made_at="2026-09-19T20:00:00+08:00")
    board = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))
    board["legs"]["周五001"]["fair"] = {"home": 0.7, "draw": 0.2, "away": 0.1}
    (day_dir / "jczq-legs-base.json").write_text(json.dumps(board), encoding="utf-8")

    [after] = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                               made_at="2026-09-20T04:00:00+08:00")

    assert after == before


def test_rebuild_before_kickoff_still_refreshes_the_read(tmp_path):
    root = _day(tmp_path)
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    [before] = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                                made_at="2026-09-19T20:00:00+08:00")

    [after] = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                               made_at="2026-09-19T21:00:00+08:00")

    assert after["read_id"] != before["read_id"]


def test_reads_carry_kind_board_key_code_and_override_marks_kind(tmp_path):
    """判断唯一事实 P0/P1：Read 自报 kind/board_key/code；有改判账即 kind=override。"""
    from nutmeg.decision.overrides import record_override

    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    board = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))
    board["legs"]["周五002"] = {
        "match_id": "m-2", "name": "C-D", "competition": "x",
        "kickoff_bj": "2026-09-20T03:00:00+08:00",
        "fair": {"home": 0.4, "draw": 0.3, "away": 0.3}, "hhad_line": None,
        "judgment_tier": "price_only", "faces": "310",
    }
    (day_dir / "jczq-legs-base.json").write_text(json.dumps(board), encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)

    reads = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                             made_at="2026-09-19T14:00:00+08:00")

    researched, market = reads
    assert (researched["kind"], researched["board_key"], researched["code"]) == (
        "research", "jczq:2026-09-19", "周五001")
    assert researched["override"] is None
    assert (market["kind"], market["code"]) == ("market", "周五002")

    record_override(day_dir / "research-周五001.json", tilt=None, note="回到市场",
                    at="2026-09-19T14:30:00+08:00", judge="claude-main-loop",
                    prior={"home": 0.6, "draw": 0.25, "away": 0.15})
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    reads = build_jczq_reads(day="2026-09-19", jczq_dir=root,
                             made_at="2026-09-19T14:31:00+08:00")

    assert reads[0]["kind"] == "override"
    assert reads[0]["override"] == {"at": "2026-09-19T14:30:00+08:00", "note": "回到市场",
                                    "judge": "claude-main-loop"}


def test_reads_carry_the_rubric_view_when_research_has_one(tmp_path):
    from nutmeg.decision.jczq_reads import build_jczq_reads, intake_board, rubric_read_view

    root = _day(tmp_path)
    day_dir = root / "daily" / "2026-09-19"
    research = {**RESEARCH, "rubric": {"version": "r1", "items": {
        "S_anchor_side": {"answer": "home", "p": 1.0, "abstain": False, "coerced": False,
                          "source": "", "captured_at": None, "note": ""},
        "F_absence_home": {"answer": None, "p": None, "abstain": True, "coerced": True,
                           "source": "", "captured_at": None, "note": ""}},
        "belief": {"3": 0.6, "1": 0.25, "0": 0.15}, "coerced": ["F_absence_home: 答是但无来源 → 弃权"]}}
    (day_dir / "research-周五001.json").write_text(json.dumps(research, ensure_ascii=False),
                                                   encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    [read] = build_jczq_reads(day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00")
    view = read["rubric"]
    assert view["version"] == "r1" and view["items"]["S_anchor_side"]["answer"] == "home"
    assert view["items"]["F_absence_home"]["coerced"] is True and "note" not in view["items"]["S_anchor_side"]
    assert view["reader_belief"] == {"3": 0.6, "1": 0.25, "0": 0.15} and view["shift"] is None
    assert view["coerced"] == ["F_absence_home: 答是但无来源 → 弃权"]
    derived = {"derived_from": "rubric:r1", "shift": {"3": 4, "1": -2, "0": -2},
               "evidence": [{"item": "F_absence_away", "pp": 4}]}
    assert rubric_read_view(research["rubric"], {"tilt": derived})["item_pp"] == {"F_absence_away": 4}
    assert rubric_read_view(None, None) is None
