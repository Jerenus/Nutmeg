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
