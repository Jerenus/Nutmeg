"""反证矩阵 ACH-lite（2026-10-27 探照灯 P3）：只由研究字段派生，同号证据不进表。"""
import json

from nutmeg.decision.counter_matrix import (
    build_matrix,
    hypotheses,
    issue_matrices,
    render_issue,
    render_matrix,
)

FAIR = {"home": 0.62, "draw": 0.23, "away": 0.15}


def _research(**over):
    base = {
        "anchor_side": "home",
        "stance": {"face": "3", "structure": "double", "cover": "1", "alt_face": "0",
                   "falsifier": "客队 90 分钟赢球则作废"},
        "strength_balance": {"underdog_path": {"side": "away", "strength": "weak"}, "events": []},
        "rubric": {"items": {}}, "license_questions": {}, "death_three_proofs": {},
        "crash_markers": [], "nondirectional_flags": [],
    }
    base.update(over)
    return base


def test_hypotheses_take_anchor_from_research_then_fair_and_upset_from_cover_alt_underdog():
    assert hypotheses(_research(), FAIR) == ("3", "1", "home")
    single = _research(stance={"face": "3", "structure": "single", "alt_face": "0"})
    assert hypotheses(single, FAIR)[:2] == ("3", "0")
    bare = _research(anchor_side="none", stance={"face": "0", "structure": "single"},
                     strength_balance={"underdog_path": {"side": "home"}})
    assert hypotheses(bare, {"home": 0.2, "draw": 0.25, "away": 0.55}) == ("0", "3", "away")
    assert hypotheses(_research(stance={}, strength_balance={}), FAIR)[1] == "1"


def test_anchor_down_event_is_minus_h1_plus_h2_and_underdog_down_is_the_reverse():
    research = _research(strength_balance={
        "underdog_path": {"side": "away"},
        "events": [
            {"event": "主队中锋报销", "side": "home", "direction": "down", "grade": "major",
             "priced_in": True, "source": "https://club.example/n/1 ｜ 官宣"},
            {"event": "客队门将伤缺", "side": "away", "direction": "down", "grade": "moderate",
             "priced_in": False, "source": "据报道"},
        ]})
    m = build_matrix(research, fair=FAIR, name="甲-乙", no="7")
    by = {r["evidence"]: r for r in m["rows"]}
    assert by["主队中锋报销"]["h1"] == -1 and by["主队中锋报销"]["h2"] == 1
    assert by["主队中锋报销"]["source_url"] == "https://club.example/n/1"
    assert by["客队门将伤缺"]["h1"] == 1 and by["客队门将伤缺"]["h2"] == -1
    assert by["客队门将伤缺"]["source_text"] == "据报道"
    assert by["客队门将伤缺"]["priced_in"] is False
    assert m["rows"][0]["evidence"] == "客队门将伤缺"        # 未价的排前面
    assert m["inconsistent"] == {"h1": 1, "h2": 1} and m["hidden"] == 0


def test_same_sign_evidence_is_hidden_and_counted_not_shown():
    # H2＝客胜（0）时，「低比分平局是模态」对 3 和 0 都是 −：无区分力；无方向旗同理
    research = _research(
        stance={"face": "3", "structure": "single", "alt_face": "0", "falsifier": "x" * 12},
        rubric={"items": {"S_draw_mode": {"answer": "yes", "p": 0.6, "abstain": False}}},
        nondirectional_flags=["venue_anomaly"],
    )
    m = build_matrix(research, fair=FAIR)
    assert m["h2"] == "0" and m["rows"] == [] and m["hidden"] == 2
    # 同一条证据在 H2＝平（1）时有区分力
    research["stance"]["alt_face"] = "1"
    m = build_matrix(research, fair=FAIR)
    assert m["h2"] == "1" and [r["h2"] for r in m["rows"]] == [1] and m["hidden"] == 1


def test_rubric_fact_items_hole_license_markers_and_dead_face_all_land_as_rows():
    research = _research(
        rubric={"items": {
            "F_absence_home": {"answer": "yes", "p": 0.9, "abstain": False,
                               "source": "https://a.example/1"},
            "F_suspension": {"answer": "away", "p": 0.8, "abstain": False, "source": ""},
            "F_absence_away": {"answer": "no", "p": 0.1, "abstain": False},        # 不成立：不进
            "F_rotation": {"answer": "unknown", "abstain": True},                  # 弃权：不进
            "S_spine_intact": {"answer": "no", "p": 0.3, "abstain": False, "source": ""},
            "S_underdog_path": {"answer": "yes", "p": 0.7, "abstain": False},
        }},
        hole_location={"unit": "attack", "side": "home", "priced_in": False, "detail": "中锋缺"},
        license_questions={"q1_spine": False, "q3a_opponent_scores": False,
                           "q5_no_rotation_window": False},
        crash_markers=["opening_new_coach_debut"],
        death_three_proofs={"away": {"verdict": "dead", "detail": "无破门机制"}},
    )
    m = build_matrix(research, fair=FAIR)
    kinds = [(r["kind"], r["h1"], r["h2"]) for r in m["rows"]]
    assert ("完整度", -1, 1) in kinds and ("许可证", -1, 1) in kinds and ("标记", -1, 1) in kinds
    assert ("三证", 0, 0) not in kinds                       # H2 是平，判死客胜对两者都 0 → 隐藏
    # absence_home / suspension / spine / underdog
    assert sum(1 for r in m["rows"] if r["kind"] == "rubric") == 4
    assert m["unknowable_before_close"].startswith("欧战/杯赛后")
    assert m["loose"] is True                                   # >5 行有区分力＝打分偏松
    md = render_matrix(m)
    assert "打分偏松" in md and "[链接](https://a.example/1)" in md and "**未价**" in md
    assert "翻盘证据：客队 90 分钟赢球则作废" in md


def test_dead_upset_face_counts_double_against_h2():
    research = _research(stance={"face": "3", "structure": "single", "alt_face": "0",
                                 "falsifier": "x" * 12},
                         death_three_proofs={"away": {"verdict": "dead", "detail": "d"}})
    m = build_matrix(research, fair=FAIR)
    assert m["h2"] == "0" and m["rows"][0]["h2"] == -2 and m["rows"][0]["h1"] == 0
    assert "−−" in render_matrix(m)


def test_issue_matrices_reads_legs_base_and_research_files_and_marks_missing(tmp_path):
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26151-legs-base.json").write_text(json.dumps({"legs": {
        "1": {"name": "甲-乙", "fair": FAIR},
        "2": {"name": "丙-丁", "fair": FAIR},
    }}), encoding="utf-8")
    (zdir / "26151-research-m1.json").write_text(json.dumps(
        _research(coverage={"converged": False, "stop_reason": "budget"}), ensure_ascii=False),
        encoding="utf-8")
    out = issue_matrices(tmp_path, "26151")
    assert [m["no"] for m in out] == ["1", "2"] and out[1]["missing"] is True
    assert out[0]["coverage"] == "◇" and out[0]["stop_reason"] == "budget"
    md = render_issue("26151", out)
    assert "场 1 甲-乙｜H1 锚方面 3 vs H2 翻车面 1｜研究收敛 ◇（budget）" in md
    assert "场 2 丙-丁｜无研究原件" in md and "不回答「会不会翻」" in md
