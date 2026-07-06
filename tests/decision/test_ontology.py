from nutmeg.decision.ontology import MarketSnapshot, Match


def test_match_id_and_roundtrip():
    m = Match(
        match_id="M-2026-07-08-092",
        kickoff_at="2026-07-08T03:00:00+08:00",
        home="Mexico", away="England", competition="WC2026",
        channel_refs={"jczq_match_no": "周日092"},
    )
    assert m.id == "M-2026-07-08-092"
    assert Match.from_dict(m.to_dict()) == m


def test_snapshot_id_and_roundtrip():
    s = MarketSnapshot(
        snapshot_id="S-...-1", match_id="M-...", taken_at="2026-07-08T15:00:00+08:00",
        kind="read_time", source="sporttery",
        fair={"had": {"home": 0.46, "draw": 0.27, "away": 0.27}},
        raw_odds={"had": {"home": 2.03, "draw": 3.30, "away": 3.55}},
        lines={"hhad_line": -1.0, "ou_line": 2.5},
    )
    assert s.id == "S-...-1"
    assert MarketSnapshot.from_dict(s.to_dict()) == s
    assert s.kind in ("read_time", "closing")
