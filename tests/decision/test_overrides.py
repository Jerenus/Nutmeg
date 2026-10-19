import json

from nutmeg.decision.overrides import effective_research, load_overrides, record_override

STANCE = {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
          "falsifier": "冰岛90分钟未胜即作废", "why_not_market": "tilt_evidence",
          "tilt": {"face": "1", "expires_if": "x", "evidence": [
              {"tier": "official", "kind": "goalkeeper_change", "pp": 4, "source": "s",
               "captured_at": "2026-09-26T08:19:00+08:00"}]},
          "alt_face": "1", "market_read": "agree"}


def _research(tmp_path):
    path = tmp_path / "research-周六011.json"
    path.write_text(json.dumps({"name": "冰岛-爱沙尼亚", "confidence": 3, "stance": STANCE},
                               ensure_ascii=False), encoding="utf-8")
    return path


def test_override_never_touches_the_research_file(tmp_path):
    path = _research(tmp_path)
    before = path.read_bytes()

    record_override(path, tilt=None, note="已定价", at="2026-09-26T14:15:00+08:00",
                    judge="claude-strength-v2",
                    prior={"home": 0.745, "draw": 0.168, "away": 0.087})

    assert path.read_bytes() == before
    [row] = load_overrides(tmp_path)
    assert row["research"] == "research-周六011.json"
    assert row["original_tilt"] == STANCE["tilt"] and row["tilt"] is None
    assert round(row["research_belief"]["draw"], 3) == 0.208   # 研究原判 = prior + 官宣 4pp
    assert row["final_belief"] == {"home": 0.745, "draw": 0.168, "away": 0.087}


def test_effective_research_applies_the_latest_override(tmp_path):
    path = _research(tmp_path)
    record_override(path, tilt={"shift": {"3": -2, "1": 2, "0": 0}, "expires_if": "x",
                                "evidence": [{"tier": "inferred", "kind": "style_matchup",
                                              "pp": 2, "source": "s",
                                              "captured_at": "2026-09-26T14:15:00+08:00"}]},
                    note="减到推断档", at="2026-09-26T14:15:00+08:00",
                    judge="claude-strength-v2", prior={"home": 0.745, "draw": 0.168, "away": 0.087})

    doc = effective_research(path)

    assert doc["stance"]["tilt"]["shift"] == {"3": -2, "1": 2, "0": 0}
    assert doc["stance"]["why_not_market"] == "tilt_evidence"
    assert doc["main_loop_rulings"]["note"] == "减到推断档"
    assert doc["research_original_stance"]["tilt"] == STANCE["tilt"]


def test_override_to_market_sets_why_none(tmp_path):
    path = _research(tmp_path)
    record_override(path, tilt=None, note="跟市场", at="2026-09-26T14:15:00+08:00",
                    judge="claude-strength-v2", prior={"home": 0.745, "draw": 0.168, "away": 0.087})
    doc = effective_research(path)
    assert doc["stance"]["tilt"] is None and doc["stance"]["why_not_market"] == "none"


def test_override_on_a_rubric_research_is_marked(tmp_path):
    path = tmp_path / "research-周六012.json"
    path.write_text(json.dumps({"name": "A-B", "confidence": 3, "stance": STANCE,
                                "rubric": {"version": "r1", "items": {}}}, ensure_ascii=False),
                    encoding="utf-8")
    record_override(path, tilt=None, note="已定价", at="2026-10-02T14:15:00+08:00",
                    judge="claude", prior={"home": 0.5, "draw": 0.3, "away": 0.2})
    assert effective_research(path)["rubric_overridden"] is True
    plain = _research(tmp_path)
    record_override(plain, tilt=None, note="x", at="2026-10-02T14:15:00+08:00",
                    judge="claude", prior={"home": 0.5, "draw": 0.3, "away": 0.2})
    assert "rubric_overridden" not in effective_research(plain)


RUBRIC_RESEARCH = {
    "name": "A-B", "confidence": 3, "kickoff_bj": "2026-10-03T22:00:00+08:00",
    "stance": {**STANCE, "tilt": None, "why_not_market": "none"},
    "rubric": {"version": "r1", "items": {
        "S_anchor_side": {"answer": "home", "p": 1.0, "abstain": False, "coerced": False,
                          "source": "", "captured_at": None, "note": ""},
        "F_absence_away": {"answer": None, "p": None, "abstain": True, "coerced": True,
                           "source": "", "captured_at": None, "note": ""}},
        "belief": None, "coerced": ["F_absence_away: 答是但无来源 → 弃权"]},
}
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _rubric_research(tmp_path):
    path = tmp_path / "research-周六013.json"
    path.write_text(json.dumps(RUBRIC_RESEARCH, ensure_ascii=False), encoding="utf-8")
    return path


def test_item_level_override_derives_the_tilt_and_books_the_reason(tmp_path):
    path = _rubric_research(tmp_path)
    row = record_override(path, items={"F_suspension": {
        "answer": "away", "p": 1.0, "source": "https://club.example/official",
        "captured_at": "2026-10-03T09:00:00+08:00"}}, reason="new_official_info",
        note="官宣后补上", at="2026-10-03T10:00:00+08:00", judge="claude", prior=PRIOR,
        kickoff="2026-10-03T22:00:00+08:00")
    # 答案是 r1 问题表的版本；拨动按当前版本（r2）的上限聚合（2026-10-19）
    assert row["reason"] == "new_official_info" and row["rubric_version"] == "r1"
    assert row["tilt"]["derived_from"] == "rubric:r2+override" and row["tilt"]["shift"]["0"] < 0
    assert row["final_belief"]["away"] < PRIOR["away"] and row["research_belief"] == PRIOR
    doc = effective_research(path)
    assert doc["rubric"]["items"]["F_suspension"]["answer"] == "away"
    assert doc["research_original_rubric"]["items"]["F_absence_away"]["abstain"] is True
    assert doc["stance"]["tilt"]["derived_from"] == "rubric:r2+override"
    assert doc["stance"]["why_not_market"] == "tilt_evidence"
    assert doc["override_reason"] == "new_official_info" and doc["rubric_overridden"] is True
    assert doc["main_loop_rulings"]["reason"] == "new_official_info"


def test_rubric_research_refuses_raw_tilt_and_requires_a_reason(tmp_path):
    import pytest

    path = _rubric_research(tmp_path)
    with pytest.raises(ValueError, match="rubric"):
        record_override(path, tilt={"face": "3", "evidence": []}, note="x",
                        at="2026-10-03T10:00:00+08:00", judge="claude", prior=PRIOR)
    with pytest.raises(ValueError, match="reason"):
        record_override(path, items={"S_anchor_side": {"answer": "away"}}, note="x",
                        at="2026-10-03T10:00:00+08:00", judge="claude", prior=PRIOR)
    with pytest.raises(ValueError, match="改判项"):
        record_override(path, items={"F_absence_home": {"p": 7}}, reason="priced_in", note="x",
                        at="2026-10-03T10:00:00+08:00", judge="claude", prior=PRIOR)
    with pytest.raises(ValueError, match="reason"):
        record_override(path, to_market=True, reason="whatever", note="x",
                        at="2026-10-03T10:00:00+08:00", judge="claude", prior=PRIOR)
    row = record_override(path, to_market=True, note="回市场", at="2026-10-03T10:00:00+08:00",
                          judge="claude", prior=PRIOR)
    assert row["reason"] == "market_only" and row["tilt"] is None and row["to_market"] is True
    doc = effective_research(path)
    assert doc["stance"]["tilt"] is None and doc["stance"]["why_not_market"] == "none"
    assert doc["override_reason"] == "market_only"


def test_legacy_research_without_rubric_keeps_the_tilt_path_and_defaults_the_reason(tmp_path):
    path = _research(tmp_path)
    row = record_override(path, tilt={"shift": {"3": -2, "1": 2, "0": 0}, "expires_if": "x",
                                      "evidence": [{"tier": "inferred", "kind": "style_matchup",
                                                    "pp": 2, "source": "s",
                                                    "captured_at": "2026-09-26T14:15:00+08:00"}]},
                          note="旧式", at="2026-09-26T14:15:00+08:00", judge="claude",
                          prior={"home": 0.745, "draw": 0.168, "away": 0.087})
    assert row["reason"] == "legacy_tilt" and row["items"] is None
    assert effective_research(path)["override_reason"] == "legacy_tilt"
