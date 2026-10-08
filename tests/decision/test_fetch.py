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
from nutmeg.decision.fetch import fetch_day
from nutmeg.decision.market_data import (
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


def test_partial_coverage_does_not_overwrite_a_richer_snapshot(tmp_path):
    """晚间只抓到 2 场，不得覆盖早间已落的 10 场——部分降级是假空盘的变体。"""
    import json

    from nutmeg.data.fcom500 import MarketOdds
    from nutmeg.decision.fetch import fetch_day

    def _market() -> MarketOdds:
        return MarketOdds(
            odds={"home": 2.0, "draw": 3.4, "away": 4.0},
            fair_probability={"home": 0.5, "draw": 0.294, "away": 0.206},
            independent=True,
        )

    run_date = "2026-09-14"
    value = {
        "matchInfoList": [
            {
                "businessDate": run_date,
                "subMatchList": [
                    {
                        "matchNumStr": f"周一{i:03d}",
                        "matchStatus": "Selling",
                        "businessDate": run_date,
                    }
                    for i in range(1, 11)
                ],
            }
        ]
    }
    rich = {
        f"周一{i:03d}": {"match_winner": {"odds": {}, "fair_probability": {}}}
        for i in range(1, 11)
    }
    path = tmp_path / "daily" / run_date / "bold_odds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rich, ensure_ascii=False), encoding="utf-8")

    fetch_day(
        run_date,
        tmp_path,
        sporttery_fetcher=lambda: (value, "sporttery"),
        euro_fetcher=lambda v, d: {"周一002": {"match_winner": _market()}},
    )

    kept = json.loads(path.read_text(encoding="utf-8"))
    assert len(kept) == 10, "部分降级不得覆盖更完整的快照"


# ── API-Football 备源默认关闭（2026-09-14 用户裁定「切」）──────────────────
#
# 实测：`decision.am` 08:00 跑时 titan007 板面尚未铺开 → 备源被唤醒 → 免费档配额
# 早已耗尽 → 每次都是 HTTP 429（`decision.am.err.log` 自 2026-09-01 起 164 次），
# **一场都没补上**。而当日 17:15 的 OpenClaw 行情刷新拿到的是 titan007 12/12。
# 备源既补不上又每天刷屏，按用户裁定关掉；保留代码路径，付费档可一键开回。


def test_euro_odds_come_from_titan007_only_and_a_miss_is_reported(monkeypatch, caplog):
    """API-Football 备源 2026-10-08 删除：漏场不再有备源，但必须在日志里说出来。"""
    import logging

    import nutmeg.services.jczq_titan007_odds as t7
    from nutmeg.decision.fetch import collect_euro_odds_live

    monkeypatch.setattr(t7, "collect_bold_odds_titan007_live",
                        lambda value, *, run_date, books=None: {}, raising=False)
    with caplog.at_level(logging.WARNING, logger="nutmeg.decision.fetch"):
        odds, provenance = collect_euro_odds_live(_BOARD, run_date="2026-07-08")
    assert odds == {} and provenance == {}
    assert "titan007 漏" in caplog.text

    monkeypatch.setattr(t7, "collect_bold_odds_titan007_live",
                        lambda value, *, run_date, books=None: _bold(), raising=False)
    odds, provenance = collect_euro_odds_live(_BOARD, run_date="2026-07-08")
    assert provenance == {"周日092": "titan007"}
