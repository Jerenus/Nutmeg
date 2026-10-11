import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_brief import compile_brief, current_issue, render_brief_md, write_brief

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _w(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    root = tmp_path / "root"
    day = data / "jczq" / "daily" / "2026-09-23"
    _w(day / "jczq-legs-base.json", {"day": "2026-09-23", "legs": {
        "周三001": {
            "match_id": "match-a", "name": "阿森纳 vs 切尔西", "competition": "英超",
            "kickoff_bj": "2026-09-23T19:30:00+08:00", "home_team": "阿森纳", "away_team": "切尔西",
            "fair": {"home": 0.52, "draw": 0.26, "away": 0.22}, "hhad_line": -1,
            "judgment_tier": "deep_research", "face_status": {"3": {"status": "alive"}},
            "anchor_integrity": "pass", "confidence": 4,
            "license_questions": {"q1_spine": True}, "directional_flags": [],
            "nondirectional_flags": ["information_asymmetry"], "crash_markers": [],
            "precedents": [], "team_tags": [], "tracking_tags": [],
        },
        "周三002": {
            "match_id": "match-b", "name": "热刺 vs 富勒姆", "competition": "英超",
            "kickoff_bj": "2026-09-23T22:00:00+08:00", "home_team": "热刺", "away_team": "富勒姆",
            "fair": {"home": 0.45, "draw": 0.28, "away": 0.27}, "hhad_line": -1,
            "judgment_tier": "price_only",
        },
    }})
    _w(day / "reads.json", [
        {"read_id": "read-1", "match_id": "match-a", "judge": "ai:jczq-analyst", "status": "draft",
         "judgment_tier": "deep_research", "confidence": 4,
         "prior": {"home": 0.52, "draw": 0.26, "away": 0.22},
         "belief": {"home": 0.58, "draw": 0.24, "away": 0.18},
         "stance": {"face": "3", "structure": "double", "cover": "1", "faces": "31",
                    "why_not_market": "tilt_evidence", "tilt_applied_pp": 6,
                    "tilt_zeroed": False, "tilt_reason": "拨 6pp 向 3", "falsifier": "…"},
         "adjustment_evidence_tiers": ["official"]},
        {"read_id": "read-2", "match_id": "match-b", "judge": "market-anchor", "status": "draft",
         "judgment_tier": "price_only", "confidence": 1,
         "prior": {"home": 0.45, "draw": 0.28, "away": 0.27},
         "belief": {"home": 0.45, "draw": 0.28, "away": 0.27}},
    ])
    _w(day / "research-周三001.json", {"summary": "阿森纳主力齐整",
                                      "captured_at": "2026-09-23T10:20:00+08:00",
                                      "anchor_side": "home", "hole_location": None,
                                      "schedule": {"rotation_risk": "low", "rest_days": 6}})
    _w(day / "research-run-2026-09-23.json", {"day": "2026-09-23", "matches": [
        {"code": "周三001", "status": "done"}, {"code": "周三002", "status": "skipped_budget"}]})
    _w(day / "price-band-周三001.json", {"fair_open": {"home": 0.50}, "fair_now": {"home": 0.52},
                                        "drift_pp": 2.0, "book_disagreement_pp": 1.1})
    _w(day / "closing_odds.json", {"周三001": {"book_count": 9,
                                              "updated_at_max": "2026-09-23T11:00:00+08:00"}})
    _w(data / "analytics" / "team_strength.json", {"teams": {
        "阿森纳": {"n": 6, "record": "5-1-0", "resid_shrunk": 0.4, "market_strength": 0.61,
                "last5_resid": 0.3}}})
    _w(data / "analytics" / "rsi-loop" / "2026-09-23.json", {
        "human_actions": ["因子 C11：propose_zero"], "failed_steps": [],
        "proposals": [{"factor_id": "C11", "decision": "propose_zero"}], "verdicts": [],
        "grades": []})
    _w(data / "zucai" / "26132-issue.json", {"issue_id": "26132",
                                             "sale_deadline": "2026-09-23T21:00:00+08:00"})
    _w(data / "zucai" / "26132-prep-morning.json", {"issue": "26132", "slot": "morning",
                                                   "captured_at": "2026-09-23T11:00:00+08:00",
                                                   "n_matches": 14})
    _w(root / "experiments" / "factors.json", {"factors": [
        {"factor_id": "C11", "layer": "probability", "current_weight_pp": 0,
         "rule_name": "价格带"}]})
    return data, root


def test_current_issue_prefers_issue_whose_deadline_is_ahead(tmp_path: Path):
    data, _ = _fixture(tmp_path)
    (data / "zucai" / "26131-issue.json").write_text(
        json.dumps({"issue_id": "26131", "sale_deadline": "2026-09-20T21:00:00+08:00"}),
        encoding="utf-8")
    assert current_issue(data / "zucai", now=NOW) == "26132"


def test_current_issue_is_none_when_every_deadline_has_passed(tmp_path: Path):
    from nutmeg.decision.day_brief import latest_issue

    data, _ = _fixture(tmp_path)
    later = NOW.replace(day=29)
    assert current_issue(data / "zucai", now=later) is None       # 不再把已开奖期当在售期
    assert latest_issue(data / "zucai") == "26132"                   # 结算路径仍要最近一期
    assert current_issue(tmp_path / "nowhere", now=later) is None


def test_compile_brief_joins_every_source_into_cards(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    cards = {c["code"]: c for c in brief["jczq"]["matches"]}
    a = cards["周三001"]
    assert a["market"]["drift_pp"] == 2.0 and a["market"]["closing_books"] == 9
    assert a["strength"]["home"]["record"] == "5-1-0" and a["strength"]["away"] is None
    assert a["research"]["status"] == "done" and a["research"]["prospective"] is True
    assert a["read"]["judge"] == "ai:jczq-analyst" and a["read"]["moved_pp"] == 6.0
    assert a["ladder"] == "偏移"
    b = cards["周三002"]
    assert b["research"]["status"] == "skipped_budget" and b["ladder"] == "跟市场"
    assert brief["jczq"]["counts"] == {"matches": 2, "deep_research": 1, "price_only": 1,
                                       "drafts": 2}
    assert brief["zucai"]["issue"] == "26132"
    assert brief["zucai"]["sale_deadline"].startswith("2026-09-23T21:00")
    assert "tiers" not in brief["zucai"] and "frontier" not in brief["zucai"]   # 写手已删
    assert brief["rsi"]["human_actions"] == ["因子 C11：propose_zero"]
    assert brief["factors"][0] == {"factor_id": "C11", "layer": "probability",
                                   "current_weight_pp": 0, "rule_name": "价格带",
                                   "decision": "propose_zero"}
    assert brief["errors"] == []


def _board(data: Path) -> None:
    """26132 的 legs-base（4 单 10 双）+ 奖金模型 + 一张已登记任九票，供初稿/审票/账房块用。"""
    from nutmeg.decision.betslip import BetSlip, SlipLeg, register_slip

    single_b, single_m = {"home": 0.70, "draw": 0.18, "away": 0.12}, {"home": 0.65, "draw": 0.20,
                                                                        "away": 0.15}
    double_b, double_m = {"home": 0.45, "draw": 0.30, "away": 0.25}, {"home": 0.42, "draw": 0.30,
                                                                        "away": 0.28}
    alive = {f: {"state": "alive"} for f in ("home", "draw", "away")}
    legs = {}
    for i in range(1, 15):
        fs = "3" if i <= 4 else "31"
        legs[str(i)] = {"name": f"m{i}", "faces": fs, "confidence": 3,
                        "prior": single_m if fs == "3" else double_m,
                        "fair": single_b if fs == "3" else double_b, "face_status": alive,
                        "license_questions": {}, "anchor_integrity": "pass", "crash_markers": [],
                        "_d3": {}}
    _w(data / "zucai" / "26132-legs-base.json", {"issue": "26132", "legs": legs,
                                                 "prescription": {k: v["faces"]
                                                                  for k, v in legs.items()}})
    _w(data / "zucai" / "26132-judgment-v1.json", {k: {"action": v["faces"]}
                                                   for k, v in legs.items()})
    _w(data / "zucai" / "prize-model.json", {"channels": {
        "renjiu": {"n": 41, "a": -5.2547, "b": 1.0, "resid_sd": 0.62, "prize_median": 3774},
        "shengfucai": {"n": 38, "a": -1.6487, "b": 1.13, "resid_sd": 0.83,
                       "prize_median": 662992}}})
    _w(data / "scoreboard.json", {"tickets": {"jczq-20260920": {"net": -120, "stake": 200}}})
    faces = {str(i): "3" for i in range(1, 10)}
    slip = BetSlip(slip_id="J1", channel="renjiu", placed_at="2026-09-23", issue="26132",
                   faces=faces, legs=[SlipLeg(key=no, market="had", selections=("home",),
                                              fair=legs[no]["fair"]) for no in faces])
    register_slip(data, slip)


def test_compile_brief_builds_the_zucai_draft_reviews_slips_and_prints_the_ledger(
        tmp_path: Path):
    data, root = _fixture(tmp_path)
    _board(data)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    z = brief["zucai"]
    assert z["brief"] == {"n": 14, "favs": 0, "stanced": 0,
                          "faces": {str(i): ("3" if i <= 4 else "31") for i in range(1, 15)}}
    labels = [(d["channel"], d["label"]) for d in z["draft"]]
    assert ("renjiu", "初稿") in labels and ("shengfucai", "刹车档") in labels
    draft = next(d for d in z["draft"] if d["channel"] == "renjiu" and d["label"] == "初稿")
    # 4 单 10 双的板、帽 ¥800（2026-10-12 单票基准 400→800）：只丢场不降档 → 1单8双 ¥512
    assert draft["stake_yuan"] == 512 and draft["premium"] > 1 and draft["downgrades"] == 0
    assert draft["vetoed"] is True                     # 与已登记票 J1 共享裸单 1-4 → V2
    assert (data / "zucai" / "26132-draft.json").exists()
    [slip] = z["slips"]
    assert slip["slip_id"] == "J1" and slip["stake_yuan"] == 2 and slip["text"].startswith("1:3")
    assert brief["account"]["net"] == -120 and "止损线" in brief["account"]["line"]
    md = render_brief_md(brief)
    assert "**账房**：本月净 -120" in md and "初判：14 场" in md
    assert "**初稿·任九** ¥512（256 注，帽 ¥800）" in md and "⛔V2" in md
    assert "J1 renjiu ¥2" in md and "前沿" not in md
    # 第二次编译不重建初稿（legs-base 没变）
    before = (data / "zucai" / "26132-draft.json").stat().st_mtime
    compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    assert (data / "zucai" / "26132-draft.json").stat().st_mtime == before


def test_compile_brief_degrades_block_by_block(tmp_path: Path):
    brief = compile_brief(data_dir=tmp_path / "none", date="2026-09-23", root=tmp_path, now=NOW)
    assert brief["jczq"]["matches"] == [] and brief["zucai"]["issue"] is None
    assert brief["rsi"] is None and brief["factors"] == []
    assert brief["zucai"]["draft"] == [] and brief["jczq"]["slips"] == []
    assert "line" in brief["account"]
    assert any("jczq-legs-base.json" in e for e in brief["errors"])


def test_research_after_kickoff_is_not_prospective(tmp_path: Path):
    data, root = _fixture(tmp_path)
    p = data / "jczq" / "daily" / "2026-09-23" / "research-周三001.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["captured_at"] = "2026-09-23T20:00:00+08:00"
    p.write_text(json.dumps(doc), encoding="utf-8")
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    assert brief["jczq"]["matches"][0]["research"]["prospective"] is False


def test_render_and_write_brief(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    md = render_brief_md(brief)
    assert "# 当日报告 · 2026-09-23" in md and "周三001" in md and "26132" in md
    assert "只解释已产生的判断" in md
    path = write_brief(data, "2026-09-23", brief)
    assert path.name == "brief.json" and (path.parent / "brief.md").exists()


def test_card_carries_stance_and_md_shows_it(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    a = brief["jczq"]["matches"][0]
    assert a["stance"]["faces"] == "31" and a["stance"]["tilt_applied_pp"] == 6
    assert a["read"]["tiers"] == ["official"]
    md = render_brief_md(brief)
    assert "押3·31" in md


def test_cards_no_longer_carry_machine_ticket_shapes(tmp_path: Path):
    """2026-10-08：「三种默认票型 × 审计码」列是机器出票时代的残留，随 day_audit 删除。"""
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    assert "audit" not in brief["jczq"]["matches"][0]


def test_failures_land_in_missing_inputs_instead_of_looking_empty(tmp_path: Path, monkeypatch):
    """登记簿读不出 ≠ 没登记；初稿重建失败 ≠ 拿旧初稿顶替（2026-10-08 检查）。"""
    import nutmeg.decision.betslip as betslip
    import nutmeg.decision.zucai_draft as zucai_draft

    data, root = _fixture(tmp_path)
    _board(data)

    def broken(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(betslip, "load_slips", broken)
    monkeypatch.setattr(zucai_draft, "build_draft", broken)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    assert brief["zucai"]["draft"] == [] and brief["zucai"]["slips"] == []
    assert any(e.startswith("已登记的票读不出") for e in brief["errors"])
    assert any("机器初稿重建失败" in e for e in brief["errors"])
    md = render_brief_md(brief)
    assert "## 缺席的输入" in md and "初稿：未出（构建失败" in md
