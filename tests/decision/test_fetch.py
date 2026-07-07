"""decision-fetch:体彩盘口 + 国际欧赔数据自取。

落盘路径必须与 sense_day 读取路径字节兼容(sporttery_markets.json + bold_odds.json
在 <output_dir>/daily/<run_date>/),故用 sense 用的 loader 反读做 schema 断言。
两个 fetcher 注入替身 → 不打网。
"""
import json
import types
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.decision.fetch import fetch_day, fetch_zucai
from nutmeg.decision.market_data import (
    load_bold_odds_snapshot,
    load_sporttery_snapshot,
)
from nutmeg.interfaces.cli import app

runner = CliRunner()

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}, "hhad": {}, "ttg": {}, "crs": {}}]}]}


def _bold():
    return {"周日092": {"match_winner": MarketOdds(
        odds={"home": 2.03, "draw": 3.30, "away": 3.55},
        fair_probability={"home": 0.45, "draw": 0.28, "away": 0.27},
        independent=True, line=None, bookmaker_count=12,
    )}}


def test_fetch_day_writes_both_snapshots(tmp_path):
    msg = fetch_day(
        "2026-07-08", tmp_path,
        sporttery_fetcher=lambda: (_BOARD, "sporttery"),
        euro_fetcher=lambda value, run_date: _bold(),
    )
    daily = tmp_path / "daily" / "2026-07-08"
    assert (daily / "sporttery_markets.json").exists()
    assert (daily / "bold_odds.json").exists()
    # 用 sense 用的 loader 反读 → 字节兼容 + schema 对
    assert load_sporttery_snapshot("2026-07-08", tmp_path) == _BOARD
    bold = load_bold_odds_snapshot("2026-07-08", tmp_path)
    assert set(bold) == {"周日092"}
    mo = bold["周日092"]["match_winner"]
    assert isinstance(mo, MarketOdds)
    assert mo.fair_probability["home"] == 0.45
    assert "体彩 1 场" in msg and "欧赔 1 场" in msg


def test_fetch_day_degrades_when_euro_fails(tmp_path):
    def _euro(value, run_date):
        raise RuntimeError("api-football down")

    msg = fetch_day(
        "2026-07-08", tmp_path,
        sporttery_fetcher=lambda: (_BOARD, "sporttery"),
        euro_fetcher=_euro,
    )
    daily = tmp_path / "daily" / "2026-07-08"
    assert (daily / "sporttery_markets.json").exists()   # 体彩仍落盘
    assert not (daily / "bold_odds.json").exists()       # 欧赔失败→不写,不崩
    assert "欧赔 0 场" in msg


def test_fetch_day_empty_euro_writes_no_bold(tmp_path):
    msg = fetch_day(
        "2026-07-08", tmp_path,
        sporttery_fetcher=lambda: (_BOARD, "sporttery"),
        euro_fetcher=lambda value, run_date: {},
    )
    assert not (tmp_path / "daily" / "2026-07-08" / "bold_odds.json").exists()
    assert "欧赔 0 场" in msg


def test_fetched_snapshots_feed_sense_day(tmp_path):
    """端到端:fetch_day 落盘 → sense_day 直接消费(证明字节兼容)。"""
    from nutmeg.decision.ontology import MarketSnapshot
    from nutmeg.decision.sense import sense_day
    from nutmeg.decision.store import DecisionStore

    fetch_day(
        "2026-07-08", tmp_path,
        sporttery_fetcher=lambda: (_BOARD, "sporttery"),
        euro_fetcher=lambda value, run_date: _bold(),
    )
    store = DecisionStore(tmp_path / "decision")
    n = sense_day("2026-07-08", output_dir=tmp_path,
                  taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1
    sources = {s.source for s in store.load(MarketSnapshot)}
    assert sources == {"sporttery", "apifootball"}


def test_decision_fetch_cli(tmp_path, monkeypatch):
    # CLI 无 fetcher 注入槽 → monkeypatch 模块级默认 fetcher 避打网。
    monkeypatch.setattr("nutmeg.decision.fetch._default_sporttery_fetcher",
                        lambda: (_BOARD, "sporttery"))
    monkeypatch.setattr("nutmeg.decision.fetch._default_euro_fetcher",
                        lambda value, run_date: _bold())
    result = runner.invoke(app, ["decision-fetch", "--run-date", "2026-07-08",
                                 "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    daily = tmp_path / "daily" / "2026-07-08"
    assert (daily / "sporttery_markets.json").exists()
    assert (daily / "bold_odds.json").exists()
    assert "体彩 1 场" in result.output


# --- Task 2: decision-fetch-zucai(传统足彩数据自取)---------------------------

_ISSUE = "26091"
_ZMATCHES = [{"match_no": 1, "competition": "英超", "home_team": "曼城",
              "away_team": "阿森纳", "match_date": "2026-07-08"}]
_ZODDS = [{"match_no": 1, "home": 2.0, "draw": 3.2, "away": 3.5}]


class _StubScheduleSync:
    """ZucaiSourceSyncService 替身:写 <issue>-issue.json,记录 sync 调用参数。"""
    def __init__(self, issue=_ISSUE, matches=None):
        self.issue = issue
        self.matches = _ZMATCHES if matches is None else matches
        self.calls: list[dict] = []

    def sync(self, *, output_dir, registry_file, **kwargs):
        self.calls.append({"output_dir": output_dir,
                           "registry_file": registry_file, **kwargs})
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{self.issue}-issue.json").write_text(
            json.dumps({"draw_date": "2026-07-08", "matches": self.matches},
                       ensure_ascii=False), encoding="utf-8")
        return types.SimpleNamespace(parsed_count=1)


class _StubOddsSync:
    """ZucaiOddsSyncService 替身:按 slot 写 <issue>-odds*.json,记录参数。"""
    def __init__(self, issue=_ISSUE, rows=None):
        self.issue = issue
        self.rows = _ZODDS if rows is None else rows
        self.calls: list[dict] = []

    def sync(self, *, output_dir, registry_file, issue_id, slot, **kwargs):
        self.calls.append({"output_dir": output_dir, "registry_file": registry_file,
                           "issue_id": issue_id, "slot": slot, **kwargs})
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        name = (f"{issue_id}-odds.json" if slot == "afternoon"
                else f"{issue_id}-odds-revision.json")
        (out / name).write_text(
            json.dumps({"issue_id": issue_id, "matches": self.rows},
                       ensure_ascii=False), encoding="utf-8")
        return types.SimpleNamespace(parsed_count=len(self.rows))


def test_fetch_zucai_writes_issue_and_odds(tmp_path):
    sched, odds = _StubScheduleSync(), _StubOddsSync()
    msg = fetch_zucai(_ISSUE, tmp_path, sync=sched, odds_sync=odds)
    assert (tmp_path / f"{_ISSUE}-issue.json").exists()
    assert (tmp_path / f"{_ISSUE}-odds.json").exists()        # afternoon 默认
    # 两个 sync 都触发,落盘目录 = zucai_dir,registry 默认 zucai_dir/issues.json
    assert sched.calls[0]["output_dir"] == tmp_path
    assert Path(sched.calls[0]["registry_file"]) == tmp_path / "issues.json"
    assert odds.calls[0]["issue_id"] == _ISSUE and odds.calls[0]["slot"] == "afternoon"
    assert _ISSUE in msg


def test_fetch_zucai_revision_slot(tmp_path):
    sched, odds = _StubScheduleSync(), _StubOddsSync()
    fetch_zucai(_ISSUE, tmp_path, sync=sched, odds_sync=odds, slot="revision")
    assert (tmp_path / f"{_ISSUE}-odds-revision.json").exists()
    assert not (tmp_path / f"{_ISSUE}-odds.json").exists()
    assert odds.calls[0]["slot"] == "revision"


def test_fetch_zucai_odds_failure_degrades(tmp_path):
    class _Boom:
        def sync(self, **kwargs):
            raise RuntimeError("odds source unavailable")

    sched = _StubScheduleSync()
    msg = fetch_zucai(_ISSUE, tmp_path, sync=sched, odds_sync=_Boom())
    assert (tmp_path / f"{_ISSUE}-issue.json").exists()       # 期表仍落盘
    assert not (tmp_path / f"{_ISSUE}-odds.json").exists()    # 赔率失败→不写,不崩
    assert "赔率 0" in msg


def test_fetched_zucai_feeds_sense_zucai(tmp_path):
    """端到端:fetch_zucai 落盘 → sense_zucai 直接消费(证明字节兼容)。"""
    from nutmeg.decision.ontology import MarketSnapshot
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore

    fetch_zucai(_ISSUE, tmp_path, sync=_StubScheduleSync(), odds_sync=_StubOddsSync())
    store = DecisionStore(tmp_path / "decision")
    n = sense_zucai(_ISSUE, output_dir=tmp_path,
                    taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1
    snaps = store.load(MarketSnapshot)
    assert snaps and snaps[0].source == "zucai"


def test_decision_fetch_zucai_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("nutmeg.decision.fetch._default_zucai_sync",
                        lambda: _StubScheduleSync())
    monkeypatch.setattr("nutmeg.decision.fetch._default_zucai_odds_sync",
                        lambda: _StubOddsSync())
    result = runner.invoke(app, ["decision-fetch-zucai", "--issue", _ISSUE,
                                 "--zucai-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{_ISSUE}-issue.json").exists()
    assert (tmp_path / f"{_ISSUE}-odds.json").exists()
    assert _ISSUE in result.output
