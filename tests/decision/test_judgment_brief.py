import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.decision.judgment_brief import jczq_brief, render_jczq, render_zucai, zucai_brief
from nutmeg.interfaces.cli import app

DAY = "2026-10-03"


def _day(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    day_dir = data / "jczq" / "daily" / DAY
    day_dir.mkdir(parents=True)
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"day": DAY, "legs": {
        "周六001": {"match_id": "m-1", "name": "曼城-纽卡",
                  "kickoff_bj": f"{DAY}T22:00:00+08:00",
                  "fair": {"home": 0.62, "draw": 0.22, "away": 0.16},
                  "judgment_tier": "deep_research",
                  "stance": {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
                             "faces": "31"},
                  "directional_flags": ["coach_debut"], "nondirectional_flags": [],
                  "note": "曼城主帅首秀。阵容齐整，纽卡客场疲软"},
        "周六002": {"match_id": "m-2", "name": "伯恩利-富勒姆",
                  "kickoff_bj": f"{DAY}T22:00:00+08:00",
                  "fair": {"home": 0.40, "draw": 0.28, "away": 0.32},
                  "judgment_tier": "price_only",
                  "directional_flags": [], "nondirectional_flags": [], "note": ""},
    }}, ensure_ascii=False), encoding="utf-8")
    (day_dir / "reads.json").write_text(json.dumps([
        {"match_id": "m-1", "prior": {"home": 0.62, "draw": 0.22, "away": 0.16},
         "belief": {"home": 0.65, "draw": 0.21, "away": 0.14}, "kind": "override",
         "judge": "ai:jczq-analyst",
         "override": {"note": "改判：纽卡前锋确认缺阵", "at": "x", "judge": "claude-main-loop"},
         "stance": {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
                    "faces": "31"},
         "confidence": 3},
        {"match_id": "m-2", "prior": {"home": 0.40, "draw": 0.28, "away": 0.32},
         "belief": {"home": 0.40, "draw": 0.28, "away": 0.32}, "kind": "market",
         "judge": "market-anchor"},
    ], ensure_ascii=False), encoding="utf-8")
    (day_dir / "closing_odds.json").write_text(json.dumps({"周六001": {"sharp": {
        "fair_probability": {"home": 0.72, "draw": 0.17, "away": 0.11}}}}), encoding="utf-8")
    return data


def test_jczq_brief_rows_market_belief_stance_kind_and_favourite(tmp_path: Path) -> None:
    data = _day(tmp_path)
    brief = jczq_brief(data, DAY)
    assert brief["n"] == 2 and brief["researched"] == 1 and brief["favs"] == 1
    a, b = brief["rows"]
    assert a["code"] == "周六001" and a["market"] == "62/22/16" and a["belief"] == "65/21/14"
    assert a["stance"] == "双 31（信心3）" and a["kind"] == "改判" and a["fav"] == "★3 72%"
    assert a["flags"] == "coach_debut" and a["note"].startswith("改判：纽卡前锋确认缺阵")
    assert b["same_as_market"] is True and b["kind"] == "市场"
    assert b["fav"] == "" and b["stance"] == "—"
    text = render_jczq(brief)
    assert "| 周六002 | 伯恩利-富勒姆 | 22:00 | 40/28/32 | 跟市场 | — | — |" in text
    assert a["rubric"] == "—"
    assert "本包不含票面" in text


def test_zucai_brief_reads_legs_base_and_judgment_v1(tmp_path: Path) -> None:
    data = tmp_path / "data"
    zdir = data / "zucai"
    zdir.mkdir(parents=True)
    (zdir / "26135-issue.json").write_text(json.dumps({"issue_id": "26135", "matches": [
        {"match_no": 1, "home_team": "曼城", "away_team": "纽卡"}]}, ensure_ascii=False),
        encoding="utf-8")
    (zdir / "26135-legs-base.json").write_text(json.dumps({"issue": "26135", "legs": {"1": {
        "name": "曼城-纽卡", "prior": {"home": 0.62, "draw": 0.22, "away": 0.16},
        "fair": {"home": 0.72, "draw": 0.18, "away": 0.10}, "faces": "3",
        "research_stance": {"face": "3", "structure": "single", "confidence": 4}}}},
        ensure_ascii=False), encoding="utf-8")
    (zdir / "26135-judgment-v1.json").write_text(
        json.dumps({"1": {"action": "3", "note": "锚方完整"}}, ensure_ascii=False),
        encoding="utf-8")
    brief = zucai_brief(data, "26135")
    [row] = brief["rows"]
    assert row["market"] == "62/22/16" and row["belief"] == "72/18/10" and row["faces"] == "3"
    assert row["action"] == "3" and row["stance"] == "单 3（信心4）"
    assert row["fav"] == ""                                   # 大热按市场 prior 0.62 < 0.70
    assert "足彩初稿不省略" in render_zucai(brief)


def test_zucai_brief_renders_directional_flag_pairs(tmp_path: Path) -> None:
    """research_intake 把方向性旗归一成 [旗名, 面] 二元组；26134 起 brief 拼接时崩 TypeError。"""
    data = tmp_path / "data"
    zdir = data / "zucai"
    zdir.mkdir(parents=True)
    (zdir / "26134-legs-base.json").write_text(json.dumps({"issue": "26134", "legs": {"1": {
        "name": "甲-乙", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2}, "faces": "31",
        "directional_flags": [["anchor_shield_out", "1"]],
        "nondirectional_flags": ["two_way_instability"]}}}), encoding="utf-8")
    [row] = zucai_brief(data, "26134")["rows"]
    assert row["flags"] == "anchor_shield_out→1、two_way_instability"


def test_jczq_brief_renders_directional_flag_pairs(tmp_path: Path) -> None:
    """竞彩同样是 [旗名, 面] 二元组；10-06 周二004 带方向旗，初判包崩 TypeError。

    （足彩 26134 已修过同一处。）
    """
    data = _day(tmp_path)
    legs_path = data / "jczq" / "daily" / DAY / "jczq-legs-base.json"
    doc = json.loads(legs_path.read_text(encoding="utf-8"))
    doc["legs"]["周六001"]["directional_flags"] = [["suspension_breaker_out", "1"]]
    doc["legs"]["周六001"]["nondirectional_flags"] = ["venue_anomaly"]
    legs_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    a, _b = jczq_brief(data, DAY)["rows"]
    assert a["flags"] == "suspension_breaker_out→1、venue_anomaly"


def test_cli_brief_prints_and_writes(tmp_path: Path) -> None:
    data = _day(tmp_path)
    result = CliRunner().invoke(app, ["judgment", "brief", "--day", DAY, "--data-dir", str(data),
                                      "--write"])
    assert result.exit_code == 0, result.output
    assert "初判与解读 · 竞彩" in result.output
    assert (data / "jczq" / "daily" / DAY / "judgment-brief.md").exists()
    bad = CliRunner().invoke(app, ["judgment", "brief", "--data-dir", str(data)])
    assert bad.exit_code == 2


_LOAD_ROW = {"home_load": {"rest_days": 3, "matches_14d": 4, "next_days": None,
                           "long_break": False},
             "away_load": {"rest_days": 19, "matches_14d": 0, "next_days": 3,
                           "long_break": True},
             "flags": ["单边密集:home", "负荷差≥2:home", "下场≤3天:away", "长歇:away"],
             "absences": {"home": ["缺阵"], "away": []}}


def test_jczq_brief_shows_the_team_load_cell_from_the_ledger(tmp_path: Path) -> None:
    """损耗台账（2026-10-09）只展示：初判包多一列，不改 belief。"""
    data = _day(tmp_path)
    (data / "jczq" / "daily" / DAY / "team-load.json").write_text(
        json.dumps({"rows": {"周六001": _LOAD_ROW}}, ensure_ascii=False), encoding="utf-8")
    brief = jczq_brief(data, DAY)
    a, b = brief["rows"]
    assert a["load"] == "休3/19 14天4/0 ⚑密主 ⇢客 ⏸客 主缺" and b["load"] == "—"
    text = render_jczq(brief)
    assert "| 损耗 |" in text and "休息差历史上已被定价" in text


def test_zucai_brief_shows_the_team_load_cell_from_the_ledger(tmp_path: Path) -> None:
    data = tmp_path / "data"
    zdir = data / "zucai"
    zdir.mkdir(parents=True)
    (zdir / "26136-legs-base.json").write_text(json.dumps({"issue": "26136", "legs": {"1": {
        "name": "甲-乙", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2}, "faces": "31"}}}),
        encoding="utf-8")
    (zdir / "26136-team-load.json").write_text(
        json.dumps({"rows": {"1": _LOAD_ROW}}, ensure_ascii=False), encoding="utf-8")
    brief = zucai_brief(data, "26136")
    assert brief["rows"][0]["load"].startswith("休3/19 14天4/0")
    assert "| 损耗 |" in render_zucai(brief)
