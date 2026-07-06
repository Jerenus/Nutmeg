import json

from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}, "hhad": {}, "ttg": {}, "crs": {}}]}]}


class _MO:
    def __init__(self, fair):
        self.fair_probability = fair
        self.line = None


def test_sense_day_persists_both_sporttery_and_euro(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    # monkeypatch 欧赔读取为一份内存 bold_odds（避免打网/依赖 MarketOdds 反序列化）
    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(
        sense_mod, "_load_euro_bold_odds",
        lambda rd, od: {"周日092": {"match_winner":
                                    _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}},
    )
    store = DecisionStore(tmp_path / "decision")
    n = sense_day("2026-07-08", output_dir=tmp_path,
                  taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1                                    # 1 场
    snaps = store.load(MarketSnapshot)
    sources = {s.source for s in snaps}
    assert sources == {"sporttery", "apifootball"}   # 两条读时快照
    euro = next(s for s in snaps if s.source == "apifootball")
    assert abs(sum(euro.fair["had"].values()) - 1.0) < 1e-6


def test_sense_day_without_euro_still_persists_sporttery(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds", lambda rd, od: {})
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-08", output_dir=tmp_path, taken_at="t", store=store)
    sources = {s.source for s in store.load(MarketSnapshot)}
    assert sources == {"sporttery"}                  # 欧赔缺→只体彩,不崩


def test_sense_day_skips_euro_for_matches_not_in_today_board(tmp_path, monkeypatch):
    """bold_odds 含次日场(跨日竞彩号)时,只给今天体彩在售场落欧赔锚,不产孤儿。"""
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")

    class _MO2:
        def __init__(self, fair):
            self.fair_probability = fair
            self.line = None

    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds", lambda rd, od: {
        "周日092": {"match_winner": _MO2({"home": 0.42, "draw": 0.28, "away": 0.30})},
        "周一099": {"match_winner": _MO2({"home": 0.50, "draw": 0.25, "away": 0.25})},
    })
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-08", output_dir=tmp_path, taken_at="t", store=store)
    euro = [s for s in store.load(MarketSnapshot) if s.source == "apifootball"]
    assert len(euro) == 1 and euro[0].match_id.endswith("周日092")   # 099 被过滤
