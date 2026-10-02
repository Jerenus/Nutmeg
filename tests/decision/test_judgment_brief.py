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


def test_cli_brief_prints_and_writes(tmp_path: Path) -> None:
    data = _day(tmp_path)
    result = CliRunner().invoke(app, ["judgment", "brief", "--day", DAY, "--data-dir", str(data),
                                      "--write"])
    assert result.exit_code == 0, result.output
    assert "初判与解读 · 竞彩" in result.output
    assert (data / "jczq" / "daily" / DAY / "judgment-brief.md").exists()
    bad = CliRunner().invoke(app, ["judgment", "brief", "--data-dir", str(data)])
    assert bad.exit_code == 2
