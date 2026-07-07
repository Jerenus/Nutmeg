# tests/decision/test_zucai_sense.py
import json

import pytest

from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.sense_zucai import zucai_snapshots


class _ZM:
    def __init__(self, no, h, a):
        self.match_no = no
        self.home_team = h
        self.away_team = a
        self.competition = ""          # 对齐真 ZucaiMatch 接口(sense_zucai 现读该字段)


def test_zucai_snapshots_canonical_and_fair():
    matches = [_ZM(3, "阿根廷", "埃及")]
    odds = {3: {"home": 1.30, "draw": 4.50, "away": 9.00}}    # 1X2 赔率
    snaps = zucai_snapshots(matches, odds, issue="26091",
                            dates={3: "2026-07-06"},
                            taken_at="2026-07-06T15:00:00+08:00")
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.match_id == "M-2026-07-06-阿根廷-埃及"            # canonical(与竞彩对齐)
    assert s.source == "zucai"
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6      # 去水
    assert s.fair["had"]["home"] > s.fair["had"]["away"]      # 短赔=高概率


def test_zucai_snapshots_skip_missing_odds():
    assert zucai_snapshots([_ZM(1, "甲", "乙")], {}, issue="26091",
                           dates={1: "2026-07-06"}, taken_at="t") == []


def test_zucai_snapshots_skip_missing_date():
    """有赔率但无该场日期 → 跳过(不伪造,不用 issue 级单日兜底)。"""
    assert zucai_snapshots([_ZM(1, "甲", "乙")],
                           {1: {"home": 1.5, "draw": 4.0, "away": 6.0}},
                           issue="26070", dates={}, taken_at="t") == []


def test_zucai_snapshots_per_match_date():
    """一期跨多天:每场 canonical 用自身日期(不是 issue 级单日)。"""
    matches = [_ZM(1, "甲", "乙"), _ZM(2, "丙", "丁")]
    odds = {1: {"home": 1.5, "draw": 4.0, "away": 6.0},
            2: {"home": 2.0, "draw": 3.3, "away": 3.6}}
    dates = {1: "2026-05-02", 2: "2026-05-03"}
    snaps = zucai_snapshots(matches, odds, issue="26070", dates=dates, taken_at="t")
    ids = {s.match_id for s in snaps}
    assert ids == {"M-2026-05-02-甲-乙", "M-2026-05-03-丙-丁"}


def test_sense_zucai_persists_matches_and_snapshots(tmp_path):
    from nutmeg.decision.ontology import MarketSnapshot, Match
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(tmp_path / "decision")

    def _loader(issue, output_dir):
        return (
            [_ZM(3, "阿根廷", "埃及"), _ZM(4, "瑞士", "哥伦比亚")],
            {3: {"home": 1.30, "draw": 4.50, "away": 9.00},
             4: {"home": 2.10, "draw": 3.20, "away": 3.60}},
            {3: "2026-07-06", 4: "2026-07-07"},          # 每场自身日期
        )
    n = sense_zucai("26091", output_dir=tmp_path, taken_at="t", store=store,
                    loader=_loader)
    assert n == 2
    assert len(store.load(MarketSnapshot)) == 2
    m = [x for x in store.load(Match) if x.home == "阿根廷"][0]
    assert m.channel_refs.get("zucai") == {"issue": "26091", "index": 3}
    assert m.match_id == "M-2026-07-06-阿根廷-埃及"           # 用自身日期
    # 跨日期第二场也各自对齐
    m4 = [x for x in store.load(Match) if x.home == "瑞士"][0]
    assert m4.match_id == "M-2026-07-07-瑞士-哥伦比亚"


def _write_issue(tmp_path, issue, matches):
    (tmp_path / f"{issue}-issue.json").write_text(
        json.dumps({"issue_id": issue, "draw_date": "2026-05-03",
                    "matches": matches}, ensure_ascii=False),
        encoding="utf-8")


def _write_odds(path, matches):
    path.write_text(json.dumps({"matches": matches}, ensure_ascii=False),
                    encoding="utf-8")


def test_default_loader_parses_issue_and_odds(tmp_path):
    from nutmeg.decision.sense_zucai import _default_loader

    _write_issue(tmp_path, "26070", [
        {"match_no": 1, "competition": "英超", "home_team": "甲", "away_team": "乙",
         "match_date": "2026-05-02"},
        {"match_no": 2, "competition": "德甲", "home_team": "丙", "away_team": "丁",
         "match_date": "2026-05-03"},
    ])
    _write_odds(tmp_path / "26070-odds.json", [
        {"match_no": 1, "home": 1.5, "draw": 4.0, "away": 6.0},
        {"match_no": 2, "home": 2.0, "draw": 3.3, "away": 3.6},
    ])
    matches, odds, dates = _default_loader("26070", tmp_path)
    assert {m.match_no for m in matches} == {1, 2}
    a = [m for m in matches if m.match_no == 1][0]
    assert a.home_team == "甲" and a.away_team == "乙"
    assert odds[1] == {"home": 1.5, "draw": 4.0, "away": 6.0}
    assert dates == {1: "2026-05-02", 2: "2026-05-03"}          # per-match date


def test_default_loader_picks_latest_odds_slot(tmp_path):
    import os

    from nutmeg.decision.sense_zucai import _default_loader

    _write_issue(tmp_path, "26070", [
        {"match_no": 1, "competition": "英超", "home_team": "甲", "away_team": "乙",
         "match_date": "2026-05-02"}])
    old = tmp_path / "26070-odds-revision.json"      # 早盘(旧)
    _write_odds(old, [{"match_no": 1, "home": 9.9, "draw": 9.9, "away": 9.9}])
    new = tmp_path / "26070-odds.json"               # 下午盘(新)
    _write_odds(new, [{"match_no": 1, "home": 1.5, "draw": 4.0, "away": 6.0}])
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))

    _, odds, _ = _default_loader("26070", tmp_path)
    assert odds[1] == {"home": 1.5, "draw": 4.0, "away": 6.0}   # 取最新槽


def test_default_loader_missing_files_raise(tmp_path):
    from nutmeg.decision.sense_zucai import _default_loader

    with pytest.raises(FileNotFoundError):
        _default_loader("99999", tmp_path)              # issue 缺失
    _write_issue(tmp_path, "26070", [
        {"match_no": 1, "competition": "英超", "home_team": "甲", "away_team": "乙",
         "match_date": "2026-05-02"}])
    with pytest.raises(FileNotFoundError):
        _default_loader("26070", tmp_path)              # 有 issue 无 odds


def test_sense_zucai_fills_competition_and_resolved_ids(tmp_path):
    """zucai 路径同样修 competition 丢失 + resolve(loader 注入,不打网)。"""
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore
    from nutmeg.domain.zucai import ZucaiMatch

    def loader(issue, output_dir):
        matches = [ZucaiMatch(match_no=1, competition="瑞超", home_team="哈马比",
                              away_team="卡尔马", match_date="2026-07-12")]
        odds = {1: {"home": 2.0, "draw": 3.2, "away": 3.4}}
        return matches, odds, {1: "2026-07-12"}

    store = DecisionStore(tmp_path)
    n = sense_zucai("26100", output_dir=tmp_path, taken_at="t",
                    store=store, loader=loader)
    assert n == 1
    m = store.load(Match)[0]
    assert m.competition == "瑞超"                    # 之前被硬编码 "" 丢掉
    assert m.home_team_id == "swe-hammarby"          # 种子实体别名命中
    assert m.away_team_id == "swe-kalmar"
    assert m.competition_id == "swe-allsvenskan"
