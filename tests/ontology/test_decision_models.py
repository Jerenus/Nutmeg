from nutmeg.ontology.decision.models import (
    CommitmentTier,
    FactorStatus,
    ForecastStatus,
    SessionStatus,
    mint_decision_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert ForecastStatus.DRAFT.value == "draft"
    assert ForecastStatus.COMMITTED.value == "committed"
    assert ForecastStatus.SUPERSEDED.value == "superseded"
    assert ForecastStatus.WITHDRAWN.value == "withdrawn"
    assert FactorStatus.PROBATION.value == "probation"
    assert FactorStatus.ACTIVE.value == "active"
    assert FactorStatus.RETIRED.value == "retired"
    assert CommitmentTier.FOLLOW.value == "follow"
    assert SessionStatus.OPEN.value == "open"


def test_mint_decision_id_is_prefixed_and_unique() -> None:
    a = mint_decision_id("fr")
    assert a.startswith("fr-")
    assert a != mint_decision_id("fr")
