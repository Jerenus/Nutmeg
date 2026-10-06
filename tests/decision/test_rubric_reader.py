import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.rubric_reader import (
    READER_PROMPT,
    kappa,
    read_file,
    read_many,
    read_rubric,
    report,
    sidecar_path,
    state_text,
)

BJ = timezone(timedelta(hours=8))
RESEARCH = {
    "name": "A-B", "code": "周五001", "match_id": "m-1",
    "summary": "主队中卫 X 官宣伤缺（club.example 10-02）",
    "captured_at": "2026-10-02T09:00:00+08:00", "kickoff_bj": "2026-10-03T22:00:00+08:00",
    "confidence": 3, "anchor_side": "home", "anchor_integrity": "fail",
    "sources": ["https://club.example/news"],
    "strength_balance": {"verdict": "home_edge", "home_state": "缺 X", "away_state": "齐整",
                         "events": [{"event": "X 伤缺", "side": "home", "direction": "down",
                                     "grade": "major", "source": "https://club.example/news"}]},
    "stance": {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
               "falsifier": "x", "why_not_market": "none", "tilt": None},
    "rubric": {"version": "r1", "items": {
        "F_absence_home": {"p": 0.9, "source": "https://club.example/news",
                           "captured_at": "2026-10-02T08:00:00+08:00"},
        "S_anchor_side": {"answer": "home"},
        "S_spine_intact": {"p": 0.2, "source": "s", "captured_at": "2026-10-02T08:00:00+08:00"}}},
}
B_OUT = json.dumps({"version": "r1", "items": {
    "F_absence_home": {"p": 0.85, "source": "https://club.example/news",
                       "captured_at": "2026-10-02T09:00:00+08:00"},
    "F_absence_away": {"p": 0.9},                       # 无来源 → 强制弃权
    "S_anchor_side": {"answer": "home"},
    "S_spine_intact": {"p": 0.6, "source": "s", "captured_at": "2026-10-02T09:00:00+08:00"},
    "M_market_read": {"answer": "agree"}},
    "belief": {"3": 0.5, "1": 0.3, "0": 0.2}})


def _fake(system, stdin):
    assert "stance" not in stdin and "rubric" not in stdin
    return 0, "好的，答案：\n" + B_OUT


def test_state_text_excludes_the_analyst_conclusions_and_prompt_lists_items():
    text = state_text(RESEARCH)
    assert "summary: " in text and "strength_balance.events" in text
    assert "stance" not in text and "rubric" not in text and "confidence" not in text
    assert "F_absence_home" in READER_PROMPT and "弃权永远正确" in READER_PROMPT


def test_read_rubric_parses_validates_and_coerces_unsourced_yes():
    norm = read_rubric(RESEARCH, kickoff=RESEARCH["kickoff_bj"], claude=_fake)
    assert norm["items"]["F_absence_home"]["answer"] == "yes"
    assert norm["items"]["F_absence_away"]["abstain"] and norm["items"]["F_absence_away"]["coerced"]
    assert norm["belief"] == {"3": 0.5, "1": 0.3, "0": 0.2}
    free = read_rubric(RESEARCH, kickoff=RESEARCH["kickoff_bj"], free=True,
                       claude=lambda s, i: (0, '{"belief": {"3": 0.6, "1": 0.25, "0": 0.15}}'))
    assert free["belief"]["3"] == 0.6 and all(r["abstain"] for r in free["items"].values())


def test_kappa_counts_only_items_both_readers_answered():
    from nutmeg.decision.rubric import validate_rubric

    a, _ = validate_rubric(RESEARCH["rubric"], kickoff=RESEARCH["kickoff_bj"])
    b = read_rubric(RESEARCH, kickoff=RESEARCH["kickoff_bj"], claude=_fake)
    k = kappa(a, b)
    # 两读都答了：F_absence_home(yes/yes)、S_anchor_side(home/home)、S_spine_intact(no/yes)
    assert k["n"] == 3 and k["items"]["F_absence_home"] is True
    assert k["items"]["S_spine_intact"] is False and k["items"]["F_absence_away"] is None
    assert kappa(a, a)["kappa"] == 1.0 and kappa(None, b)["n"] == 0


def test_read_file_writes_a_sidecar_once_and_report_aggregates(tmp_path: Path):
    day = tmp_path / "jczq" / "daily" / "2026-10-02"
    day.mkdir(parents=True)
    path = day / "research-周五001.json"
    path.write_text(json.dumps(RESEARCH, ensure_ascii=False), encoding="utf-8")
    assert sidecar_path(path).name == "rubric-周五001.json"
    from nutmeg.decision.rubric_reader import research_files
    (day / "research-run-2026-10-02.json").write_text("{}", encoding="utf-8")
    (day / "research-周五002.rejected.json").write_text("{}", encoding="utf-8")
    assert research_files(tmp_path, day="2026-10-02") == [path]      # 运行日志/拒收件不算研究
    assert sidecar_path(Path("/z/26135-research-m3.json")).name == "26135-rubric-m3.json"
    from nutmeg.decision.rubric_reader import code_of
    assert code_of(Path("/z/26135-research-m3.json")) == "3"
    assert code_of(Path("/d/research-周六001.json")) == "周六001"
    assert code_of(path, RESEARCH) == "周五001"
    now = datetime(2026, 10, 2, 10, 45, tzinfo=BJ)
    doc = read_file(path, claude=_fake, now=now)
    assert doc["prospective"] is True and doc["kappa"]["n"] == 3 and doc["model"] == "haiku"
    assert sidecar_path(path).exists()
    assert read_file(path, claude=_fake, now=now) is None          # 已有侧车不重跑
    out = read_many([path, day / "research-周五009.json"], claude=_fake)
    assert out["skipped"] == ["research-周五001.json"] and len(out["failed"]) == 1
    rep = report(tmp_path, day="2026-10-02")
    assert rep["n_sidecars"] == 1 and rep["item_agreement"]["F_absence_home"] == (1.0, 1)
    assert rep["kappa_mean"] is not None
    md = (tmp_path / "analytics" / "rubric" / "2026-10-02.md").read_text("utf-8")
    assert "判断 rubric 两读 · 2026-10-02" in md and "| F_absence_home | 1.00 | 1 |" in md
    after = read_file(path, claude=lambda s, i: (0, '{"belief": {"3": 0.4, "1": 0.3, "0": 0.3}}'),
                      free=True, now=now)
    assert after["b_free"]["belief"]["3"] == 0.4 and after["b"]["items"]  # free 补跑保留 b


def test_reader_tolerates_illegal_options_instead_of_failing_the_file():
    from nutmeg.decision.rubric_reader import tolerate

    out = read_rubric(RESEARCH, kickoff=RESEARCH["kickoff_bj"], claude=lambda s, i: (0, json.dumps({
        "version": "r1", "items": {"F_goalkeeper": {"answer": "both", "p": 0.9, "source": "s",
                                                     "captured_at": "2026-10-02T09:00:00+08:00"},
                                   "S_underdog_path": {"p": 1.7}, "S_anchor_side": "home",
                                   "Z_nope": {"p": 1}}})))
    assert out["items"]["F_goalkeeper"]["abstain"] and out["items"]["S_underdog_path"]["abstain"]
    assert out["items"]["S_anchor_side"]["answer"] == "home"
    assert "Z_nope" not in out["items"]
    assert tolerate({"F_goalkeeper": {"answer": "both"}})["F_goalkeeper"]["_tolerated"]
    assert tolerate("junk") == {}
    from nutmeg.decision.rubric_reader import tolerate_belief
    assert tolerate_belief({"3": 0.7, "1": 0.9}) is None and tolerate_belief("x") is None
    assert tolerate_belief({"3": 0.5, "1": 0.3, "0": 0.25})["3"] == 0.5 / 1.05
    bad = read_rubric(RESEARCH, kickoff=RESEARCH["kickoff_bj"], claude=lambda s, i: (0, json.dumps(
        {"version": "r1", "items": {}, "belief": {"3": 2, "1": 2}})))
    assert bad["belief"] is None


def test_read_many_runs_concurrently_and_keeps_order(tmp_path: Path):
    day = tmp_path / "jczq" / "daily" / "2026-10-02"
    day.mkdir(parents=True)
    paths = []
    for i in range(1, 6):
        path = day / f"research-周五00{i}.json"
        path.write_text(json.dumps({**RESEARCH, "code": f"周五00{i}"}, ensure_ascii=False),
                        encoding="utf-8")
        paths.append(path)
    out = read_many(paths, claude=_fake, workers=3)
    assert out["done"] == [p.name for p in paths] and not out["failed"]
    again = read_many(paths, claude=_fake, workers=3)
    assert again["skipped"] == [p.name for p in paths]
    rep = report(tmp_path, day="2026-10-02")
    assert rep["n_sidecars"] == 5 and rep["n_a_missing"] == 0


def test_kickoff_comes_from_schedule_board_legs_or_the_zucai_issue(tmp_path: Path):
    from nutmeg.decision.rubric_reader import research_kickoff

    day = tmp_path / "jczq" / "daily" / "2026-10-05"
    day.mkdir(parents=True)
    (day / "jczq-legs-base.json").write_text(json.dumps(
        {"legs": {"周一002": {"kickoff_bj": "2026-10-06T02:45:00+08:00"}}}), "utf-8")
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26135-issue.json").write_text(json.dumps(
        {"matches": [{"match_no": 1, "kickoff_bj": "2026-10-06 19:35"}]}), "utf-8")
    scheduled = {"schedule": {"kickoff_bj": "2026-10-06T00:00:00+08:00"}}
    assert research_kickoff(day / "research-周一001.json", scheduled) == "2026-10-06T00:00:00+08:00"
    assert research_kickoff(day / "research-周一002.json", {}) == "2026-10-06T02:45:00+08:00"
    assert research_kickoff(zdir / "26135-research-m1.json", {}) == "2026-10-06T19:35"
    assert research_kickoff(zdir / "26135-research-m9.json", {}) is None
    # 旧研究的 schedule 是一句话：当没写，落到板面兜底，不崩（2026-10-06 重测时撞到）
    prose = {"schedule": "周一 02:45 开球，主队三天两赛"}
    assert research_kickoff(day / "research-周一002.json", prose) == "2026-10-06T02:45:00+08:00"


def test_pending_research_is_unstarted_and_unread_and_sidecar_is_prospective(tmp_path: Path):
    from nutmeg.decision.rubric_reader import pending_research

    now = datetime(2026, 10, 5, 12, 30, tzinfo=BJ)
    day = tmp_path / "jczq" / "daily" / "2026-10-05"
    day.mkdir(parents=True)
    later = {**RESEARCH, "kickoff_bj": None,
             "schedule": {"kickoff_bj": "2026-10-06T00:00:00+08:00"}}
    started = {**RESEARCH, "kickoff_bj": "2026-10-05T12:00:00+08:00"}
    (day / "research-周一001.json").write_text(json.dumps(later), "utf-8")
    (day / "research-周一002.json").write_text(json.dumps(later), "utf-8")
    (day / "rubric-周一002.json").write_text("{}", "utf-8")                 # already read
    (day / "research-周一003.json").write_text(json.dumps(started), "utf-8")
    (day / "research-周一004.rejected.json").write_text(json.dumps(later), "utf-8")
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26135-issue.json").write_text(json.dumps({"matches": [
        {"match_no": 1, "kickoff_bj": "2026-10-06 19:35"},
        {"match_no": 2, "kickoff_bj": "2026-10-05 03:00"}]}), "utf-8")
    zucai = {k: v for k, v in RESEARCH.items() if k not in ("kickoff_bj", "code")}
    (zdir / "26135-research-m1.json").write_text(json.dumps(zucai), "utf-8")
    (zdir / "26135-research-m2.json").write_text(json.dumps(zucai), "utf-8")

    paths = pending_research(tmp_path, now=now)
    assert [p.name for p in paths] == ["research-周一001.json", "26135-research-m1.json"]
    doc = read_file(paths[1], claude=_fake, now=now)
    assert doc["prospective"] is True
