from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.decision.ontology import MarketSnapshot


class _MO:
    """MarketOdds 的最小替身：只需 fair_probability / line。"""
    def __init__(self, fair, line=None):
        self.fair_probability = fair
        self.line = line


def test_euro_snapshot_from_bold_odds_builds_had_fair():
    bold = {"周日092": {"match_winner": _MO({"home": 0.40, "draw": 0.28, "away": 0.32})}}
    snaps = euro_snapshot_from_bold_odds(
        bold, run_date="2026-07-08", taken_at="2026-07-08T15:00:00+08:00",
        kind="read_time", source="apifootball",
    )
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.source == "apifootball" and s.kind == "read_time"
    assert s.match_id == "M-2026-07-08-周日092"
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6
    assert s.fair["had"]["home"] == 0.40
    assert "tags" not in s.to_dict()      # 净化不变


def test_euro_snapshot_skips_match_without_fair():
    bold = {"周日091": {"match_winner": _MO({})}}     # 空 fair
    assert euro_snapshot_from_bold_odds(
        bold, run_date="2026-07-08", taken_at="t", kind="read_time",
        source="apifootball") == []
