"""decision-fetch:体彩盘口 + 国际欧赔数据自取。

落盘路径必须与 sense_day 读取路径字节兼容(sporttery_markets.json + bold_odds.json
在 <output_dir>/daily/<run_date>/),故用 sense 用的 loader 反读做 schema 断言。
两个 fetcher 注入替身 → 不打网。
"""
from typer.testing import CliRunner

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.decision.fetch import fetch_day
from nutmeg.interfaces.cli import app
from nutmeg.services.jczq_market_kernel import (
    load_bold_odds_snapshot,
    load_sporttery_snapshot,
)

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
