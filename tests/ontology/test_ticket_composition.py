from datetime import UTC, datetime

import pytest

from nutmeg.ontology.tickets import composition
from nutmeg.ontology.tickets.models import TicketLegDraft

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _leg(**changes: object) -> TicketLegDraft:
    values: dict[str, object] = {
        "leg_key": "match-1:md-had:home",
        "match_id": "match-1",
        "match_no": 1,
        "name": "Home FC - Away FC",
        "market_definition_id": "md-had",
        "selection_id": "sel-had-home",
        "outcome_key": "home",
        "faces": "3",
        "forecast_revision_id": "fr-current",
        "entry_quote_id": "quote-home",
        "odds": 2.1,
        "line": None,
        "bucket": "main",
        "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "confidence": 4,
        "directional_flags": (),
        "nondirectional_flags": (),
        "anchor_integrity": "pass",
        "precedents": (),
    }
    values.update(changes)
    return TicketLegDraft(**values)


def test_compose_batch_calls_authoritative_functions(monkeypatch) -> None:
    leg = _leg()
    calls: list[tuple[str, object]] = []

    def fake_compose(legs, budget, **kwargs):
        calls.append(("compose", (legs, budget, kwargs)))
        return {
            "channel": "jczq",
            "period_cap_yuan": 400,
            "total_stake_yuan": 100,
            "scaled": False,
            "n_tickets": 1,
            "tickets": [
                {
                    "ticket_id": "T-1",
                    "bucket": "main",
                    "budget_bucket": "had_modal",
                    "structure": "single",
                    "stake_yuan": 100,
                    "combined_odds": 2.1,
                    "n_legs": 1,
                    "computed_hit_prob": 0.6,
                    "legs": [leg.express_dict()],
                }
            ],
            "by_bucket": {
                "main": {"cap": 100, "stake": 100, "n_tickets": 1}
            },
        }

    def fake_audit(legs):
        calls.append(("audit", legs))
        return []

    monkeypatch.setattr(composition, "compose_tickets", fake_compose)
    monkeypatch.setattr(composition, "audit_legs", fake_audit)

    result = composition.compose_batch([leg], channel="jczq", made_at=AT)

    assert [call[0] for call in calls] == ["compose", "audit"]
    assert result.total_stake_yuan == 100
    assert result.tickets[0].legs[0]["forecast_revision_id"] == "fr-current"


def test_empty_slate_is_legal_and_has_no_findings() -> None:
    result = composition.compose_batch([], channel="jczq", made_at=AT)

    assert result.is_empty is True
    assert result.total_stake_yuan == 0
    assert result.tickets == ()
    assert result.findings == ()


def test_findings_are_normalized_without_losing_rule_provenance() -> None:
    result = composition.compose_batch(
        [_leg(confidence=3)], channel="jczq", made_at=AT
    )

    finding = next(item for item in result.findings if item.code == "low_conf_single")
    assert finding.level == "ERROR"
    assert finding.match_no == 1
    assert "conf3" in finding.message
    assert finding.since == "判决表 m 条"
    assert result.has_blocking is True


def test_canonical_digest_is_mapping_order_independent_and_materially_sensitive() -> None:
    left = {"ticket": {"amount": 100, "legs": ["home"]}, "channel": "jczq"}
    reordered = {"channel": "jczq", "ticket": {"legs": ["home"], "amount": 100}}
    changed = {"channel": "jczq", "ticket": {"legs": ["draw"], "amount": 100}}

    assert composition.canonical_digest(left) == composition.canonical_digest(reordered)
    assert composition.canonical_digest(left) != composition.canonical_digest(changed)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"faces": ""}, "faces"),
        ({"faces": "33"}, "faces"),
        ({"faces": "2"}, "faces"),
        ({"odds": 1.0}, "odds"),
        ({"forecast_revision_id": " "}, "forecast_revision_id"),
        ({"fair": {"home": 0.8, "draw": 0.3, "away": 0.1}}, "sum"),
    ],
)
def test_ticket_leg_rejects_invalid_deterministic_inputs(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _leg(**changes)


def test_ticket_leg_express_and_audit_views_are_explicit() -> None:
    leg = _leg(
        faces="31",
        directional_flags=(("self_made_tail", "1"),),
        precedents=(("0", "same venue away win", "alive"),),
    )

    express = leg.express_dict()
    audit = leg.audit_leg()

    assert express == {
        "leg_key": "match-1:md-had:home",
        "match_id": "match-1",
        "market": "md-had",
        "selection": "home",
        "selection_id": "sel-had-home",
        "forecast_revision_id": "fr-current",
        "entry_quote_id": "quote-home",
        "odds": 2.1,
        "line": None,
        "bucket": "main",
        "prob": 0.6,
    }
    assert audit.faces == "31"
    assert audit.directional_flags == (("self_made_tail", "1"),)
    assert audit.precedents == (("0", "same venue away win", "alive"),)


def test_ticket_leg_roundtrips_c8_adjustment_inputs() -> None:
    leg = _leg(
        prior={"home": 0.55, "draw": 0.30, "away": 0.15},
        adjustment_evidence_tiers=("confirmed_structural", "inference"),
    )

    restored = TicketLegDraft.from_dict(leg.to_dict())
    audit = restored.audit_leg()

    assert restored.prior == {"home": 0.55, "draw": 0.30, "away": 0.15}
    assert restored.adjustment_evidence_tiers == (
        "confirmed_structural",
        "inference",
    )
    assert audit.prior == restored.prior
    assert audit.adjustment_evidence_tiers == restored.adjustment_evidence_tiers


def test_ticket_leg_rejects_unknown_adjustment_evidence_tier() -> None:
    with pytest.raises(ValueError, match="adjustment_evidence_tiers"):
        _leg(adjustment_evidence_tiers=("press_rumor",))
