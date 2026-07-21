from nutmeg.ontology.ingest.sporttery import ParsedMatch, parse_sporttery_markets

# Mirrors the real sporttery getMatchCalculatorV1 shape:
# matchInfoList[].subMatchList[], Chinese team names, matchNumStr as the cross-channel
# key, matchId as the globally-unique provider id, and matchDate + matchTime carrying
# the true calendar instant (Beijing) so early-morning games already land on the next day.
SPORTTERY_FIXTURE = {
    "matchInfoList": [
        {
            "businessDate": "2026-07-19",
            "subMatchList": [
                {
                    "matchStatus": "Selling", "businessDate": "2026-07-19",
                    "matchNumStr": "周日001", "matchNum": 7001, "matchId": 2040001,
                    "matchDate": "2026-07-19", "matchTime": "23:30:00",
                    "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK",
                    "leagueAbbName": "瑞典超",
                    "had": {"h": "2.10", "d": "3.30", "a": "3.10"},
                },
                {
                    "matchStatus": "Selling", "businessDate": "2026-07-19",
                    "matchNumStr": "周日104", "matchNum": 7104, "matchId": 2040541,
                    "matchDate": "2026-07-20", "matchTime": "03:00:00",
                    "homeTeamAbbName": "西班牙", "awayTeamAbbName": "阿根廷",
                    "leagueAbbName": "世界杯",
                    "had": {"h": "1.80", "d": "3.60", "a": "4.20"},
                },
            ],
        }
    ]
}


def test_parses_provider_id_and_teams() -> None:
    parsed = parse_sporttery_markets(SPORTTERY_FIXTURE, business_date="2026-07-19")
    first = parsed[0]
    assert isinstance(first, ParsedMatch)
    assert first.provider == "sporttery"
    assert first.external_id == "2040001"    # matchId — globally unique
    assert first.match_no == "周日001"        # matchNumStr — cross-channel key
    assert first.home_name == "哈马比"
    assert first.away_name == "AIK"
    assert first.league_name == "瑞典超"
    assert first.scheduled_at.startswith("2026-07-19T23:30:00")
    assert {q.outcome_key for q in first.quotes} == {"home", "draw", "away"}


def test_early_morning_kickoff_uses_matchdate_next_day() -> None:
    parsed = parse_sporttery_markets(SPORTTERY_FIXTURE, business_date="2026-07-19")
    wc = next(m for m in parsed if m.match_no == "周日104")
    # matchDate 2026-07-20 + matchTime 03:00 = next calendar day, never clamped to businessDate
    assert wc.scheduled_at.startswith("2026-07-20T03:00:00")
    assert wc.schedule_status == "scheduled"


def test_missing_time_yields_unknown_not_a_guess() -> None:
    fixture = {"matchInfoList": [{"businessDate": "2026-07-19", "subMatchList": [
        {"matchStatus": "Selling", "businessDate": "2026-07-19", "matchNumStr": "周日009",
         "matchNum": 7009, "matchId": 2040009, "matchDate": "", "matchTime": "",
         "homeTeamAbbName": "A", "awayTeamAbbName": "B", "leagueAbbName": "X", "had": {}}]}]}
    parsed = parse_sporttery_markets(fixture, business_date="2026-07-19")
    assert parsed[0].scheduled_at is None
    assert parsed[0].schedule_status == "unknown"
