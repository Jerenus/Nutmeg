# tests/decision/test_zucai_sense.py
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.sense_zucai import zucai_snapshots


class _ZM:
    def __init__(self, no, h, a):
        self.match_no = no
        self.home_team = h
        self.away_team = a


def test_zucai_snapshots_canonical_and_fair():
    matches = [_ZM(3, "阿根廷", "埃及")]
    odds = {3: {"home": 1.30, "draw": 4.50, "away": 9.00}}    # 1X2 赔率
    snaps = zucai_snapshots(matches, odds, issue="26091", match_date="2026-07-06",
                            taken_at="2026-07-06T15:00:00+08:00")
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.match_id == "M-2026-07-06-阿根廷-埃及"            # canonical(与竞彩对齐)
    assert s.source == "zucai"
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6      # 去水
    assert s.fair["had"]["home"] > s.fair["had"]["away"]      # 短赔=高概率


def test_zucai_snapshots_skip_missing_odds():
    assert zucai_snapshots([_ZM(1, "A", "B")], {}, issue="26091",
                           match_date="2026-07-06", taken_at="t") == []
