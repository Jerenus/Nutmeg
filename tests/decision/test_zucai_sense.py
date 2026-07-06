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
            "2026-07-06",
        )
    n = sense_zucai("26091", output_dir=tmp_path, taken_at="t", store=store,
                    loader=_loader)
    assert n == 2
    assert len(store.load(MarketSnapshot)) == 2
    m = [x for x in store.load(Match) if x.home == "阿根廷"][0]
    assert m.channel_refs.get("zucai") == {"issue": "26091", "index": 3}
