from nutmeg.ontology.evidence.models import (
    Availability,
    ClaimStatus,
    LineupRole,
    LineupStatus,
    StatusKind,
    VerificationMethod,
    mint_evidence_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert Availability.OUT.value == "out"
    assert Availability.DOUBTFUL.value == "doubtful"
    assert StatusKind.INJURY.value == "injury"
    assert LineupStatus.CONFIRMED.value == "confirmed"
    assert LineupRole.STARTER.value == "starter"
    assert ClaimStatus.PROVISIONAL.value == "provisional"
    assert ClaimStatus.VERIFIED.value == "verified"
    assert VerificationMethod.DETERMINISTIC.value == "deterministic"


def test_mint_evidence_id_is_prefixed_and_unique() -> None:
    first = mint_evidence_id("claim")
    assert first.startswith("claim-")
    assert first != mint_evidence_id("claim")
    assert mint_evidence_id("obs").startswith("obs-")
