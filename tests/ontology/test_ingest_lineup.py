from nutmeg.ontology.ingest.lineup import ParsedAvailability, parse_availability_snapshot

SNAPSHOT = {"match_no": "周日001", "team": "哈马比", "players": [
    {"name": "Striker A", "provider_id": "P-1", "availability": "out", "status_kind": "injury"},
    {"name": "Mid B", "provider_id": "P-2", "availability": "available",
     "status_kind": "selection"},
]}


def test_parses_availability_rows() -> None:
    parsed = parse_availability_snapshot(SNAPSHOT)
    assert all(isinstance(p, ParsedAvailability) for p in parsed)
    out = next(p for p in parsed if p.availability == "out")
    assert out.player_name == "Striker A"
    assert out.provider_id == "P-1"
    assert out.status_kind == "injury"
    assert out.match_no == "周日001"
    assert out.team_name == "哈马比"
