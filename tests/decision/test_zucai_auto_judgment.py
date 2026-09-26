import json

from nutmeg.decision.zucai_auto_judgment import auto_judgment, build_auto_reads

STANCE = {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
          "falsifier": "主队90分钟不胜即作废", "why_not_market": "tilt_evidence",
          "tilt": {"shift": {"3": 2, "1": 0, "0": -2}, "expires_if": "x", "evidence": [
              {"tier": "state", "kind": "form_state", "pp": 2, "source": "s",
               "captured_at": "2026-09-26T10:00:00+08:00"}]},
          "alt_face": "1", "market_read": "agree"}


def _issue(tmp_path, n=3):
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26133-issue.json").write_text(json.dumps({
        "issue_id": "26133", "sale_deadline": "2026-09-26 20:30",
        "matches": [{"match_no": i, "home_team": f"H{i}", "away_team": f"A{i}",
                     "competition": "c", "kickoff_bj": "2026-09-27 19:35"}
                    for i in range(1, n + 1)]}),
        encoding="utf-8")
    (zdir / "26133-store-ids.json").write_text(json.dumps({str(i): {
        "match_no": i, "match_id": f"z-{i}", "snapshot_id": f"s-{i}", "name": f"H{i}-A{i}",
        "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}} for i in range(1, n + 1)}),
        encoding="utf-8")
    return zdir


def _research(zdir, no, **over):
    doc = {"name": "x", "summary": "主队更完整", "confidence": 3, "anchor_side": "home",
           "anchor_integrity": "pass", "directional_flags": [], "nondirectional_flags": [],
           "crash_markers": [], "precedents": [], "license_questions": {},
           "death_three_proofs": {}, "stance": STANCE, **over}
    (zdir / f"26133-research-m{no}.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                     encoding="utf-8")


def test_auto_judgment_transcribes_research_and_anchors_the_rest_to_market(tmp_path):
    zdir = _issue(tmp_path, n=2)
    _research(zdir, 1)

    judgment = auto_judgment(issue="26133", data_dir=tmp_path)

    researched, bare = judgment["1"], judgment["2"]
    assert researched["action"] == "31" and researched["confidence"] == 3
    assert round(researched["belief"]["home"], 4) == 0.52
    assert researched["adjustment_evidence_tiers"] == ["state"]
    assert researched["source"] == "research"
    assert bare["action"] == "310" and bare["belief"] == {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert bare["source"] == "market_anchor" and bare["confidence"] == 1


def test_manual_main_loop_judgment_always_wins(tmp_path):
    zdir = _issue(tmp_path, n=1)
    _research(zdir, 1)
    manual = {"1": {"action": "3", "confidence": 4, "belief": {"home": 0.6, "draw": 0.25,
                                                                "away": 0.15}}}
    (zdir / "26133-judgment-v1.json").write_text(json.dumps(manual), encoding="utf-8")

    judgment = auto_judgment(issue="26133", data_dir=tmp_path)

    assert judgment["1"]["action"] == "3" and judgment["1"]["source"] == "main_loop"


def test_auto_reads_keep_main_loop_and_started_reads(tmp_path):
    zdir = _issue(tmp_path, n=2)
    _research(zdir, 1)
    _research(zdir, 2)
    existing = [
        {"read_id": "R-claude-strength-v2-zucai-26133-01-had", "match_id": "z-1",
         "judge": "claude-strength-v2", "belief": {"home": 0.7, "draw": 0.2, "away": 0.1}},
    ]
    (zdir / "26133-reads.json").write_text(json.dumps(existing), encoding="utf-8")

    reads = build_auto_reads(issue="26133", data_dir=tmp_path,
                             made_at="2026-09-26T14:15:00+08:00")

    by_match = {read["match_id"]: read for read in reads}
    assert by_match["z-1"] == existing[0]                  # 主循环 Read 不动
    assert by_match["z-2"]["judge"] == "ai-pool"
    assert by_match["z-2"]["read_id"].endswith("-02-had-r1415")
    assert json.loads((zdir / "26133-reads.json").read_text(encoding="utf-8")) == reads
