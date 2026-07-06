from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.ontology import MarketSnapshot


def _snap(source, had):
    return MarketSnapshot(snapshot_id=f"S-{source}", match_id="M-1", taken_at="t",
                          kind="read_time", source=source, fair={"had": had})


def test_prefers_euro_over_sporttery():
    euro = _snap("apifootball", {"home": 0.40, "draw": 0.30, "away": 0.30})
    tc = _snap("sporttery", {"home": 0.46, "draw": 0.27, "away": 0.27})
    prior, anchor = resolve_prior([tc, euro], market="had")
    assert prior == euro.fair["had"] and anchor.source == "apifootball"


def test_falls_back_to_sporttery_when_no_euro():
    tc = _snap("sporttery", {"home": 0.46, "draw": 0.27, "away": 0.27})
    prior, anchor = resolve_prior([tc], market="had")
    assert prior == tc.fair["had"] and anchor.source == "sporttery"


def test_none_when_no_read_time_snapshot_has_market():
    closing = MarketSnapshot(snapshot_id="S-c", match_id="M-1", taken_at="t",
                             kind="closing", source="apifootball",
                             fair={"had": {"home": 0.5, "draw": 0.3, "away": 0.2}})
    assert resolve_prior([closing], market="had") == (None, None)  # 只认 read_time
