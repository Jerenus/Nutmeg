import json

from nutmeg.decision.closing import capture_closing
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


class _MO:
    def __init__(self, fair):
        self.fair_probability = fair
        self.line = None


def test_capture_closing_persists_closing_euro_snapshot(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    # 注入 live 欧赔抓取替身（避免打网）
    def fake_live(value, *, run_date, settings=None):
        return {"周日092": {"match_winner": _MO({"home": 0.38, "draw": 0.29, "away": 0.33})}}

    n = capture_closing("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T20:00:00+08:00", store=store,
                        live_fetcher=fake_live)
    assert n == 1
    closing = [s for s in store.load(MarketSnapshot) if s.kind == "closing"]
    assert len(closing) == 1
    assert closing[0].source == "apifootball"
    assert abs(sum(closing[0].fair["had"].values()) - 1.0) < 1e-6


def test_capture_closing_no_board_returns_zero(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    assert capture_closing("2026-07-08", output_dir=tmp_path, taken_at="t",
                           store=store, live_fetcher=lambda *a, **k: {}) == 0


def test_capture_closing_empty_euro_persists_nothing(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    n = capture_closing("2026-07-08", output_dir=tmp_path, taken_at="t",
                        store=store, live_fetcher=lambda *a, **k: {})
    assert n == 0                                # 欧赔空→无收盘快照(CLV 将 null)
