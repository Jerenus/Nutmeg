from nutmeg.decision.ontology import League
from nutmeg.ontology.ingest.competition import resolve_competition_edition


def test_competition_resolution_requires_an_explicit_season() -> None:
    league = League(
        league_id="competition-test",
        name_zh="测试联赛",
        name_en="Test League",
        season="",
    )

    assert resolve_competition_edition("测试联赛", leagues=(league,)) is None


def test_competition_resolution_rejects_an_ambiguous_exact_alias() -> None:
    leagues = (
        League(
            league_id="competition-a",
            name_zh="共用简称",
            name_en="League A",
            season="2026",
        ),
        League(
            league_id="competition-b",
            name_zh="联赛 B",
            name_en="League B",
            season="2026",
            aliases=["共用简称"],
        ),
    )

    assert resolve_competition_edition("共用简称", leagues=leagues) is None
