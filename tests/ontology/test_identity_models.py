from nutmeg.ontology.identity.models import (
    EntityType,
    MatchSide,
    MatchStatus,
    ResolutionStatus,
    TeamKind,
    mint_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert EntityType.TEAM.value == "team"
    assert EntityType.MATCH.value == "match"
    assert ResolutionStatus.PROVISIONAL.value == "provisional"
    assert TeamKind.NATIONAL.value == "national"
    assert MatchSide.NEUTRAL_DESIGNATED_HOME.value == "neutral_designated_home"
    assert MatchStatus.SCHEDULED.value == "scheduled"


def test_mint_id_is_prefixed_and_unique() -> None:
    first = mint_id(EntityType.TEAM)
    second = mint_id(EntityType.TEAM)
    assert first.startswith("team-")
    assert first != second
    assert mint_id(EntityType.MATCH).startswith("match-")
