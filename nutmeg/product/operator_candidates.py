"""Deterministic, bounded ticket candidate enumeration for the operator workbench.

The caller supplies every offer, market, face bundle, and structure option. This module
only enumerates that finite space and calculates exact comparison metrics.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from itertools import combinations, product
from math import comb

from nutmeg.ontology.actions.models import canonical_json

_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_FACE_ORDER = {"3": 0, "1": 1, "0": 2}
ODDS_BAND_INTERVALS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("10x", Decimal("8"), Decimal("15")),
    ("20x", Decimal("15"), Decimal("35")),
    ("50x", Decimal("35"), Decimal("75")),
    ("100x", Decimal("75"), Decimal("150")),
)


class CandidateSpaceLimitError(ValueError):
    """The declared exhaustive space exceeds the operator's explicit bound."""

    def __init__(self, calculated_candidate_count: int, limit: int) -> None:
        self.calculated_candidate_count = calculated_candidate_count
        self.limit = limit
        super().__init__(
            f"calculated candidate count {calculated_candidate_count} exceeds limit {limit}"
        )


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _positive_int(value: int, name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _decimal_string(value: str, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal string") from error
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _quantized(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _decimal_text(value: Decimal) -> str:
    value = _quantized(value)
    return format(Decimal(0) if value == 0 else value, ".12f")


def _face_sort_key(face_code: str) -> tuple[int, str]:
    return _FACE_ORDER.get(face_code, len(_FACE_ORDER)), face_code


def _hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FaceBundleOption:
    bundle_code: str
    face_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text(self.bundle_code, "bundle_code")
        if not self.face_codes:
            raise ValueError("face_codes are required")
        if len(set(self.face_codes)) != len(self.face_codes):
            raise ValueError("face_codes must be unique")
        for face_code in self.face_codes:
            _required_text(face_code, "face_code")


@dataclass(frozen=True, slots=True)
class OfferCandidateInput:
    official_match_no: str
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    probabilities: tuple[tuple[str, str], ...]
    allowed_face_bundles: tuple[FaceBundleOption, ...]
    omission_allowed: bool
    quote_ids_by_face: tuple[tuple[str, str], ...] = ()
    booked_decimal_odds_by_face: tuple[tuple[str, str], ...] = ()
    settlement_parameter_decimal: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "official_match_no",
            "official_offer_revision_id",
            "match_id",
            "market_definition_id",
        ):
            _required_text(getattr(self, name), name)
        if not isinstance(self.omission_allowed, bool):
            raise TypeError("omission_allowed must be boolean")
        if not self.probabilities:
            raise ValueError("probabilities are required")
        probability_codes = tuple(code for code, _value in self.probabilities)
        if len(set(probability_codes)) != len(probability_codes):
            raise ValueError("probability face codes must be unique")
        parsed = tuple(
            _decimal_string(value, "probability", positive=False)
            for _code, value in self.probabilities
        )
        if any(value < _ZERO or value > _ONE for value in parsed):
            raise ValueError("probabilities must be between zero and one")
        if sum(parsed, _ZERO) != _ONE:
            raise ValueError("probabilities must sum exactly to one")
        if not self.allowed_face_bundles:
            raise ValueError("allowed_face_bundles are required")
        bundle_codes = tuple(bundle.bundle_code for bundle in self.allowed_face_bundles)
        if len(set(bundle_codes)) != len(bundle_codes):
            raise ValueError("bundle codes must be unique per offer")
        bundle_face_sets = tuple(
            frozenset(bundle.face_codes) for bundle in self.allowed_face_bundles
        )
        if len(set(bundle_face_sets)) != len(bundle_face_sets):
            raise ValueError("bundle face sets must be unique per offer")
        known_faces = set(probability_codes)
        if any(
            not set(bundle.face_codes) <= known_faces
            for bundle in self.allowed_face_bundles
        ):
            raise ValueError("face bundle references an unknown probability face")
        if self.market_definition_id == "md-crs" and any(
            "other" in bundle.face_codes for bundle in self.allowed_face_bundles
        ):
            raise ValueError(
                "CRS candidates require a direction-specific CRS aggregate"
            )
        _validated_text_pairs(self.quote_ids_by_face, "quote IDs")
        _validated_decimal_pairs(self.booked_decimal_odds_by_face, "booked odds")
        if self.settlement_parameter_decimal is not None:
            _decimal_string(
                self.settlement_parameter_decimal,
                "settlement parameter",
            )

    def probability_map(self) -> dict[str, Decimal]:
        return {
            code: _decimal_string(value, "probability")
            for code, value in self.probabilities
        }


def _validated_text_pairs(values: tuple[tuple[str, str], ...], label: str) -> None:
    keys = tuple(key for key, _value in values)
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} face codes must be unique")
    for key, value in values:
        _required_text(key, f"{label} face code")
        _required_text(value, label)


def _validated_decimal_pairs(
    values: tuple[tuple[str, str], ...],
    label: str,
) -> None:
    keys = tuple(key for key, _value in values)
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} face codes must be unique")
    for key, value in values:
        _required_text(key, f"{label} face code")
        _decimal_string(value, label, positive=True)


@dataclass(frozen=True, slots=True)
class CandidateStructureTemplate:
    kind: str
    structure_code: str
    eligible_official_match_nos: tuple[str, ...]
    required_offer_count: int
    maximum_groups: int
    pass_size: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"jczq_pass", "zucai_group"}:
            raise ValueError("unknown candidate structure kind")
        _required_text(self.structure_code, "structure_code")
        if not self.eligible_official_match_nos:
            raise ValueError("eligible_official_match_nos are required")
        if len(set(self.eligible_official_match_nos)) != len(
            self.eligible_official_match_nos
        ):
            raise ValueError("eligible_official_match_nos must be unique")
        _positive_int(self.required_offer_count, "required_offer_count")
        _positive_int(self.maximum_groups, "maximum_groups")
        if self.required_offer_count > len(self.eligible_official_match_nos):
            raise ValueError("required_offer_count exceeds eligible offers")
        if self.pass_size is not None:
            _positive_int(self.pass_size, "pass_size")


@dataclass(frozen=True, slots=True)
class CandidateGenerationInput:
    lane: str
    ticket_kind: str
    currency: str
    capital_cap_minor: int
    unit_stake_minor: int
    maximum_ticket_count: int
    maximum_exhaustive_candidate_count: int
    offers: tuple[OfferCandidateInput, ...]
    templates: tuple[CandidateStructureTemplate, ...]
    fixed_prize_policy_revision_id: str | None = None
    official_median_bonus_minor: int | None = None

    def __post_init__(self) -> None:
        if self.lane not in {"jczq", "zucai"}:
            raise ValueError("lane must be jczq or zucai")
        if self.ticket_kind not in {"jczq_pass", "sfc", "renjiu"}:
            raise ValueError("unknown ticket_kind")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise ValueError("currency must be a three-letter uppercase code")
        _positive_int(self.capital_cap_minor, "capital_cap_minor")
        _positive_int(self.unit_stake_minor, "unit_stake_minor")
        _positive_int(self.maximum_ticket_count, "maximum_ticket_count")
        _positive_int(
            self.maximum_exhaustive_candidate_count,
            "maximum_exhaustive_candidate_count",
        )
        if self.official_median_bonus_minor is not None:
            _positive_int(
                self.official_median_bonus_minor,
                "official_median_bonus_minor",
            )
        if not self.offers or not self.templates:
            raise ValueError("offers and templates are required")
        offer_numbers = tuple(offer.official_match_no for offer in self.offers)
        if len(set(offer_numbers)) != len(offer_numbers):
            raise ValueError("official match numbers must be unique")
        structure_codes = tuple(template.structure_code for template in self.templates)
        if len(set(structure_codes)) != len(structure_codes):
            raise ValueError("candidate structure codes must be unique")
        if self.lane == "jczq":
            if self.ticket_kind != "jczq_pass":
                raise ValueError("JCZQ requires jczq_pass")
            if any(template.kind != "jczq_pass" for template in self.templates):
                raise ValueError("JCZQ requires jczq_pass structures")
            if any(
                template.pass_size != template.required_offer_count
                for template in self.templates
            ):
                raise ValueError("JCZQ pass size must equal required offer count")
            for offer in self.offers:
                _require_jczq_market_bindings(offer)
        else:
            if self.ticket_kind not in {"sfc", "renjiu"}:
                raise ValueError("Zucai requires sfc or renjiu")
            _required_text(
                self.fixed_prize_policy_revision_id or "",
                "fixed_prize_policy_revision_id",
            )
            for offer in self.offers:
                if (
                    offer.quote_ids_by_face
                    or offer.booked_decimal_odds_by_face
                    or offer.settlement_parameter_decimal is not None
                ):
                    raise ValueError(
                        "Zucai candidate legs must not contain quote odds or line"
                    )
            if any(template.kind != "zucai_group" for template in self.templates):
                raise ValueError("Zucai requires zucai_group structures")
            required_count = 14 if self.ticket_kind == "sfc" else 9
            count_label = "fourteen" if self.ticket_kind == "sfc" else "nine"
            if any(
                template.required_offer_count != required_count
                for template in self.templates
            ):
                raise ValueError(
                    f"{self.ticket_kind} structures require exactly {count_label} offers"
                )


def _require_jczq_market_bindings(offer: OfferCandidateInput) -> None:
    faces = {code for code, _value in offer.probabilities}
    quote_faces = {code for code, _value in offer.quote_ids_by_face}
    odds_faces = {code for code, _value in offer.booked_decimal_odds_by_face}
    if quote_faces != faces or odds_faces != faces:
        raise ValueError("JCZQ candidate requires exact Quote and odds per face")
    if offer.market_definition_id == "md-hhad" and (
        offer.settlement_parameter_decimal is None
    ):
        raise ValueError("HHAD candidate requires a signed settlement parameter")


@dataclass(frozen=True, slots=True)
class CandidateAuditFinding:
    finding_id: str
    code: str
    severity: str
    message: str
    audit_kind: str = "legs"
    official_match_no: str | None = None
    rule_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("finding_id", "code", "message"):
            _required_text(getattr(self, name), name)
        if self.severity not in {"WARN", "ERROR"}:
            raise ValueError("candidate audit severity must be WARN or ERROR")
        if self.audit_kind not in {
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        }:
            raise ValueError("candidate audit kind is invalid")


@dataclass(frozen=True, slots=True)
class CandidateTicketLeg:
    official_match_no: str
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_codes: tuple[str, ...]
    quote_ids: tuple[str, ...]
    booked_decimal_odds: tuple[str, ...]
    settlement_parameter_decimal: str | None


@dataclass(frozen=True, slots=True)
class CandidateTicket:
    ticket_kind: str
    structure_code: str
    group_code: str
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    fixed_prize_policy_revision_id: str | None
    legs: tuple[CandidateTicketLeg, ...]
    composition_hash: str


@dataclass(frozen=True, slots=True)
class CandidateDraft:
    tickets: tuple[CandidateTicket, ...]
    stake_minor: int
    composition_hash: str


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    rank: int | None
    partition: str
    deployable: bool
    tickets: tuple[CandidateTicket, ...]
    ticket_count: int
    distinct_note_count: int
    paid_note_unit_count: int
    stake_minor: int
    cap_utilization_decimal: str
    probability_kind: str
    objective_label: str
    objective_probability_decimal: str
    expected_broken_legs_decimal: str
    common_dead_faces: tuple[tuple[str, tuple[str, ...]], ...]
    break_even_bonus_minor: int | None
    break_even_to_median_decimal: str | None
    audit_findings: tuple[CandidateAuditFinding, ...]
    content_hash: str
    odds_band: str | None = None
    target_odds_min_decimal: str | None = None
    target_odds_max_decimal: str | None = None
    combined_decimal_odds: str | None = None
    parent_candidate_revision_id: str | None = None
    delta_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateGenerationResult:
    set_kind: str
    comparison_only: bool
    calculated_candidate_count: int
    candidates: tuple[CandidateComparison, ...]
    selected_candidate_hash: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateBandResult:
    odds_band: str
    target_odds_min_decimal: str
    target_odds_max_decimal: str
    status: str
    reason_code: str | None
    candidates: tuple[CandidateComparison, ...]


@dataclass(frozen=True, slots=True)
class BandCandidateGenerationResult:
    set_kind: str
    comparison_only: bool
    calculated_candidate_count: int
    candidates: tuple[CandidateComparison, ...]
    by_band: Mapping[str, CandidateBandResult]
    selected_candidate_hash: str | None = None


def union_probability(
    tickets: Sequence[Mapping[str, frozenset[str]]],
    probabilities: Mapping[str, Mapping[str, Decimal]],
) -> Decimal:
    """Return the exact union of finite ticket-win events."""
    with localcontext() as context:
        context.prec = 50
        total = _ZERO
        for size in range(1, len(tickets) + 1):
            sign = _ONE if size % 2 else -_ONE
            for subset in combinations(tickets, size):
                total += sign * _intersection_probability(subset, probabilities)
        return _quantized(total)


def _intersection_probability(
    tickets: Sequence[Mapping[str, frozenset[str]]],
    probabilities: Mapping[str, Mapping[str, Decimal]],
) -> Decimal:
    offer_numbers = set().union(*(ticket.keys() for ticket in tickets))
    result = _ONE
    for offer_number in offer_numbers:
        restrictions = tuple(
            ticket[offer_number]
            for ticket in tickets
            if offer_number in ticket
        )
        allowed = set.intersection(*(set(value) for value in restrictions))
        if not allowed:
            return _ZERO
        try:
            result *= sum(
                (probabilities[offer_number][face] for face in allowed),
                _ZERO,
            )
        except KeyError as error:
            raise ValueError("ticket references an unknown probability face") from error
    return result


def enumerate_candidates(
    inputs: CandidateGenerationInput,
    *,
    set_kind: str = "judgment_bound",
    generator_version: str = "operator-candidate-v1",
    audit_candidate: Callable[[CandidateDraft], Sequence[CandidateAuditFinding]] | None = None,
) -> CandidateGenerationResult:
    """Enumerate every operator-declared candidate or reject before materializing any."""
    if set_kind not in {
        "judgment_bound",
        "conditional_market_counterfactual",
    }:
        raise ValueError("unknown candidate set kind")
    _required_text(generator_version, "generator_version")
    generation_fingerprint = _generation_fingerprint(
        inputs,
        set_kind=set_kind,
        generator_version=generator_version,
    )
    offer_by_number = {offer.official_match_no: offer for offer in inputs.offers}
    atomic_counts = _calculated_atomic_ticket_counts(inputs, offer_by_number)
    atomic_count = sum(atomic_counts.values())
    maximum_batch_size = min(inputs.maximum_ticket_count, atomic_count)
    calculated_count = _calculated_candidate_count(
        inputs,
        atomic_counts,
        maximum_batch_size=maximum_batch_size,
    )
    if calculated_count > inputs.maximum_exhaustive_candidate_count:
        raise CandidateSpaceLimitError(
            calculated_candidate_count=calculated_count,
            limit=inputs.maximum_exhaustive_candidate_count,
        )
    atomic = _enumerate_atomic_tickets(inputs, offer_by_number)
    if len(atomic) != atomic_count:
        raise RuntimeError("candidate enumeration count did not reconcile")
    drafts = tuple(
        _candidate_draft(batch)
        for size in range(1, maximum_batch_size + 1)
        for batch in combinations(atomic, size)
        if _batch_respects_group_limits(batch, inputs.templates)
    )
    comparisons = tuple(
        _compare_candidate(
            draft,
            inputs,
            set_kind=set_kind,
            generation_fingerprint=generation_fingerprint,
            findings=tuple(audit_candidate(draft)) if audit_candidate else (),
        )
        for draft in drafts
    )
    ordered = _ordered_candidates(comparisons)
    return CandidateGenerationResult(
        set_kind=set_kind,
        comparison_only=set_kind == "conditional_market_counterfactual",
        calculated_candidate_count=calculated_count,
        candidates=ordered,
    )


def enumerate_band_candidates(
    inputs: CandidateGenerationInput,
    *,
    set_kind: str = "judgment_bound",
    generator_version: str = "operator-candidate-v2-bands",
    audit_candidate: Callable[[CandidateDraft], Sequence[CandidateAuditFinding]]
    | None = None,
) -> BandCandidateGenerationResult:
    """Enumerate JCZQ candidates and classify auditable single-ticket odds bands."""
    if inputs.lane != "jczq":
        raise ValueError("odds-band candidate generation requires the JCZQ lane")
    base = enumerate_candidates(
        inputs,
        set_kind=set_kind,
        generator_version=generator_version,
        audit_candidate=audit_candidate,
    )
    candidates_by_band: dict[str, list[CandidateComparison]] = {
        band: [] for band, _minimum, _maximum in ODDS_BAND_INTERVALS
    }
    outside: list[CandidateComparison] = []
    for candidate in base.candidates:
        combined = _candidate_combined_odds(candidate)
        interval = _odds_band_interval(combined) if combined is not None else None
        if interval is None:
            outside.append(candidate)
            continue
        band, minimum, maximum = interval
        candidates_by_band[band].append(
            replace(
                candidate,
                odds_band=band,
                target_odds_min_decimal=_decimal_text(minimum),
                target_odds_max_decimal=_decimal_text(maximum),
                combined_decimal_odds=_decimal_text(combined),
            )
        )

    banded = [
        candidate
        for band, _minimum, _maximum in ODDS_BAND_INTERVALS
        for candidate in candidates_by_band[band]
    ]
    retained = banded + (outside if base.comparison_only else [])
    ordered = _ordered_candidates(retained)
    ordered_by_hash = {candidate.content_hash: candidate for candidate in ordered}
    by_band = {
        band: CandidateBandResult(
            odds_band=band,
            target_odds_min_decimal=_decimal_text(minimum),
            target_odds_max_decimal=_decimal_text(maximum),
            status="candidates" if candidates_by_band[band] else "no_feasible_candidate",
            reason_code=None if candidates_by_band[band] else "candidate_space_empty",
            candidates=tuple(
                ordered_by_hash[candidate.content_hash]
                for candidate in candidates_by_band[band]
            ),
        )
        for band, minimum, maximum in ODDS_BAND_INTERVALS
    }
    return BandCandidateGenerationResult(
        set_kind=base.set_kind,
        comparison_only=base.comparison_only,
        calculated_candidate_count=base.calculated_candidate_count,
        candidates=ordered,
        by_band=by_band,
    )


def _candidate_combined_odds(candidate: CandidateComparison) -> Decimal | None:
    if len(candidate.tickets) != 1:
        return None
    combined = _ONE
    for leg in candidate.tickets[0].legs:
        if len(leg.selection_codes) != 1 or len(leg.booked_decimal_odds) != 1:
            return None
        combined *= _decimal_string(
            leg.booked_decimal_odds[0],
            "booked odds",
            positive=True,
        )
    return _quantized(combined)


def _odds_band_interval(
    combined: Decimal,
) -> tuple[str, Decimal, Decimal] | None:
    return next(
        (
            (band, minimum, maximum)
            for band, minimum, maximum in ODDS_BAND_INTERVALS
            if minimum <= combined < maximum
        ),
        None,
    )


def _calculated_atomic_ticket_counts(
    inputs: CandidateGenerationInput,
    offer_by_number: Mapping[str, OfferCandidateInput],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for template in inputs.templates:
        total = 0
        eligible = _template_offers(template, offer_by_number)
        for group in combinations(eligible, template.required_offer_count):
            if _group_is_legal(group, eligible):
                bundle_product = 1
                for offer in group:
                    bundle_product *= len(offer.allowed_face_bundles)
                total += bundle_product
        counts[template.structure_code] = total
    if sum(counts.values()) < 1:
        raise ValueError("declared candidate space is empty")
    return counts


def _calculated_candidate_count(
    inputs: CandidateGenerationInput,
    atomic_counts: Mapping[str, int],
    *,
    maximum_batch_size: int,
) -> int:
    counts_by_size = {0: 1}
    limits = {
        template.structure_code: template.maximum_groups
        for template in inputs.templates
    }
    for structure_code, atomic_count in atomic_counts.items():
        next_counts: dict[int, int] = {}
        for existing_size, existing_count in counts_by_size.items():
            maximum_for_structure = min(
                atomic_count,
                limits[structure_code],
                maximum_batch_size - existing_size,
            )
            for selected_count in range(maximum_for_structure + 1):
                total_size = existing_size + selected_count
                next_counts[total_size] = next_counts.get(total_size, 0) + (
                    existing_count * comb(atomic_count, selected_count)
                )
        counts_by_size = next_counts
    return sum(
        count
        for size, count in counts_by_size.items()
        if 1 <= size <= maximum_batch_size
    )


def _batch_respects_group_limits(
    batch: Sequence[CandidateTicket],
    templates: Sequence[CandidateStructureTemplate],
) -> bool:
    limits = {template.structure_code: template.maximum_groups for template in templates}
    counts: dict[str, int] = {}
    for ticket in batch:
        counts[ticket.structure_code] = counts.get(ticket.structure_code, 0) + 1
        if counts[ticket.structure_code] > limits[ticket.structure_code]:
            return False
    return True


def _template_offers(
    template: CandidateStructureTemplate,
    offer_by_number: Mapping[str, OfferCandidateInput],
) -> tuple[OfferCandidateInput, ...]:
    try:
        offers = tuple(
            offer_by_number[number]
            for number in template.eligible_official_match_nos
        )
    except KeyError as error:
        raise ValueError("template references an unknown offer") from error
    return offers


def _group_is_legal(
    group: Sequence[OfferCandidateInput],
    eligible: Sequence[OfferCandidateInput],
) -> bool:
    selected = {offer.official_match_no for offer in group}
    return all(
        offer.omission_allowed or offer.official_match_no in selected
        for offer in eligible
    )


def _enumerate_atomic_tickets(
    inputs: CandidateGenerationInput,
    offer_by_number: Mapping[str, OfferCandidateInput],
) -> tuple[CandidateTicket, ...]:
    tickets: dict[str, CandidateTicket] = {}
    for template in inputs.templates:
        eligible = _template_offers(template, offer_by_number)
        for group in combinations(eligible, template.required_offer_count):
            if not _group_is_legal(group, eligible):
                continue
            group_code = "-".join(offer.official_match_no for offer in group)
            for bundles in product(*(offer.allowed_face_bundles for offer in group)):
                ticket = _ticket_from_bundles(inputs, template, group_code, group, bundles)
                tickets.setdefault(ticket.composition_hash, ticket)
    return tuple(tickets[key] for key in sorted(tickets))


def _ticket_from_bundles(
    inputs: CandidateGenerationInput,
    template: CandidateStructureTemplate,
    group_code: str,
    offers: Sequence[OfferCandidateInput],
    bundles: Sequence[FaceBundleOption],
) -> CandidateTicket:
    legs = tuple(
        _ticket_leg(offer, bundle, lane=inputs.lane)
        for offer, bundle in zip(offers, bundles, strict=True)
    )
    unit_count = 1
    for leg in legs:
        unit_count *= len(leg.selection_codes)
    stake_minor = inputs.unit_stake_minor * unit_count
    document = {
        "ticket_kind": inputs.ticket_kind,
        "structure_code": template.structure_code,
        "group_code": group_code,
        "currency": inputs.currency,
        "unit_stake_minor": inputs.unit_stake_minor,
        "unit_count": unit_count,
        "stake_minor": stake_minor,
        "fixed_prize_policy_revision_id": inputs.fixed_prize_policy_revision_id,
        "legs": [_leg_document(leg) for leg in legs],
    }
    return CandidateTicket(
        ticket_kind=inputs.ticket_kind,
        structure_code=template.structure_code,
        group_code=group_code,
        currency=inputs.currency,
        unit_stake_minor=inputs.unit_stake_minor,
        unit_count=unit_count,
        stake_minor=stake_minor,
        fixed_prize_policy_revision_id=inputs.fixed_prize_policy_revision_id,
        legs=legs,
        composition_hash=_hash(document),
    )


def _generation_fingerprint(
    inputs: CandidateGenerationInput,
    *,
    set_kind: str,
    generator_version: str,
) -> str:
    return _hash(
        {
            "generator_version": generator_version,
            "set_kind": set_kind,
            "lane": inputs.lane,
            "ticket_kind": inputs.ticket_kind,
            "currency": inputs.currency,
            "capital_cap_minor": inputs.capital_cap_minor,
            "unit_stake_minor": inputs.unit_stake_minor,
            "maximum_ticket_count": inputs.maximum_ticket_count,
            "maximum_exhaustive_candidate_count": (
                inputs.maximum_exhaustive_candidate_count
            ),
            "fixed_prize_policy_revision_id": inputs.fixed_prize_policy_revision_id,
            "official_median_bonus_minor": inputs.official_median_bonus_minor,
            "offers": [
                {
                    "official_match_no": offer.official_match_no,
                    "official_offer_revision_id": offer.official_offer_revision_id,
                    "match_id": offer.match_id,
                    "market_definition_id": offer.market_definition_id,
                    "probabilities": list(offer.probabilities),
                    "allowed_face_bundles": [
                        {
                            "bundle_code": bundle.bundle_code,
                            "face_codes": list(bundle.face_codes),
                        }
                        for bundle in offer.allowed_face_bundles
                    ],
                    "omission_allowed": offer.omission_allowed,
                    "quote_ids_by_face": list(offer.quote_ids_by_face),
                    "booked_decimal_odds_by_face": list(
                        offer.booked_decimal_odds_by_face
                    ),
                    "settlement_parameter_decimal": (
                        offer.settlement_parameter_decimal
                    ),
                }
                for offer in inputs.offers
            ],
            "templates": [
                {
                    "kind": template.kind,
                    "structure_code": template.structure_code,
                    "eligible_official_match_nos": list(
                        template.eligible_official_match_nos
                    ),
                    "required_offer_count": template.required_offer_count,
                    "maximum_groups": template.maximum_groups,
                    "pass_size": template.pass_size,
                }
                for template in inputs.templates
            ],
        }
    )
def _ticket_leg(
    offer: OfferCandidateInput,
    bundle: FaceBundleOption,
    *,
    lane: str,
) -> CandidateTicketLeg:
    faces = tuple(sorted(bundle.face_codes, key=_face_sort_key))
    quote_map = dict(offer.quote_ids_by_face)
    odds_map = dict(offer.booked_decimal_odds_by_face)
    return CandidateTicketLeg(
        official_match_no=offer.official_match_no,
        official_offer_revision_id=offer.official_offer_revision_id,
        match_id=offer.match_id,
        market_definition_id=offer.market_definition_id,
        selection_codes=faces,
        quote_ids=tuple(quote_map[face] for face in faces) if lane == "jczq" else (),
        booked_decimal_odds=(
            tuple(odds_map[face] for face in faces) if lane == "jczq" else ()
        ),
        settlement_parameter_decimal=offer.settlement_parameter_decimal,
    )


def _leg_document(leg: CandidateTicketLeg) -> dict[str, object]:
    return {
        "official_match_no": leg.official_match_no,
        "official_offer_revision_id": leg.official_offer_revision_id,
        "match_id": leg.match_id,
        "market_definition_id": leg.market_definition_id,
        "selection_codes": list(leg.selection_codes),
        "quote_ids": list(leg.quote_ids),
        "booked_decimal_odds": list(leg.booked_decimal_odds),
        "settlement_parameter_decimal": leg.settlement_parameter_decimal,
    }


def _candidate_draft(tickets: Sequence[CandidateTicket]) -> CandidateDraft:
    ordered = tuple(sorted(tickets, key=lambda item: item.composition_hash))
    stake_minor = sum(ticket.stake_minor for ticket in ordered)
    return CandidateDraft(
        tickets=ordered,
        stake_minor=stake_minor,
        composition_hash=_hash(
            {
                "ticket_hashes": [ticket.composition_hash for ticket in ordered],
                "stake_minor": stake_minor,
            }
        ),
    )


def _compare_candidate(
    draft: CandidateDraft,
    inputs: CandidateGenerationInput,
    *,
    set_kind: str,
    generation_fingerprint: str,
    findings: tuple[CandidateAuditFinding, ...],
) -> CandidateComparison:
    probabilities = {
        offer.official_match_no: offer.probability_map()
        for offer in inputs.offers
    }
    ticket_events = tuple(
        {
            leg.official_match_no: frozenset(leg.selection_codes)
            for leg in ticket.legs
        }
        for ticket in draft.tickets
    )
    objective = union_probability(ticket_events, probabilities)
    expected_broken = _expected_broken_legs(ticket_events, probabilities)
    break_even = (
        None
        if objective == 0
        else int(
            (Decimal(draft.stake_minor) / objective).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
    )
    median_multiple = (
        None
        if break_even is None or inputs.official_median_bonus_minor is None
        else _decimal_text(
            Decimal(break_even) / Decimal(inputs.official_median_bonus_minor)
        )
    )
    comparison_only = set_kind == "conditional_market_counterfactual"
    if draft.stake_minor > inputs.capital_cap_minor:
        partition = "over_cap"
    elif any(finding.severity == "ERROR" for finding in findings):
        partition = "audit_blocked"
    else:
        partition = "eligible"
    paid_note_unit_count = sum(ticket.unit_count for ticket in draft.tickets)
    distinct_note_count = _distinct_note_count(draft.tickets)
    return CandidateComparison(
        rank=None,
        partition=partition,
        deployable=not comparison_only and partition == "eligible",
        tickets=draft.tickets,
        ticket_count=len(draft.tickets),
        distinct_note_count=distinct_note_count,
        paid_note_unit_count=paid_note_unit_count,
        stake_minor=draft.stake_minor,
        cap_utilization_decimal=(
            _decimal_text(Decimal(draft.stake_minor) / Decimal(inputs.capital_cap_minor))
            if inputs.capital_cap_minor
            else "0.000000000000"
        ),
        probability_kind=(
            "all_required_legs"
            if len(draft.tickets) == 1
            else "any_ticket_all_required_legs"
        ),
        objective_label=(
            "P(all required legs correct)"
            if len(draft.tickets) == 1
            else "P(at least one ticket all correct)"
        ),
        objective_probability_decimal=_decimal_text(objective),
        expected_broken_legs_decimal=_decimal_text(expected_broken),
        common_dead_faces=_common_dead_faces(ticket_events, probabilities),
        break_even_bonus_minor=break_even,
        break_even_to_median_decimal=median_multiple,
        audit_findings=findings,
        content_hash=_hash(
            {
                "generation_fingerprint": generation_fingerprint,
                "composition_hash": draft.composition_hash,
            }
        ),
    )


def _distinct_note_count(tickets: Sequence[CandidateTicket]) -> int:
    notes: set[tuple[object, ...]] = set()
    for ticket in tickets:
        for selections in product(*(leg.selection_codes for leg in ticket.legs)):
            notes.add(
                (
                    ticket.ticket_kind,
                    ticket.structure_code,
                    ticket.group_code,
                    tuple(
                        (leg.official_match_no, selection)
                        for leg, selection in zip(ticket.legs, selections, strict=True)
                    ),
                )
            )
    return len(notes)


def _expected_broken_legs(
    tickets: Sequence[Mapping[str, frozenset[str]]],
    probabilities: Mapping[str, Mapping[str, Decimal]],
) -> Decimal:
    totals = []
    for ticket in tickets:
        totals.append(
            sum(
                (
                    _ONE
                    - sum(
                        (probabilities[offer][face] for face in faces),
                        _ZERO,
                    )
                    for offer, faces in ticket.items()
                ),
                _ZERO,
            )
        )
    return _ZERO if not totals else sum(totals, _ZERO) / Decimal(len(totals))


def _common_dead_faces(
    tickets: Sequence[Mapping[str, frozenset[str]]],
    probabilities: Mapping[str, Mapping[str, Decimal]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not tickets:
        return ()
    common_offers = set.intersection(*(set(ticket) for ticket in tickets))
    result = []
    for offer in sorted(common_offers):
        covered = set().union(*(ticket[offer] for ticket in tickets))
        dead = tuple(
            sorted(set(probabilities[offer]) - covered, key=_face_sort_key)
        )
        if dead:
            result.append((offer, dead))
    return tuple(result)


def _ordered_candidates(
    candidates: Sequence[CandidateComparison],
) -> tuple[CandidateComparison, ...]:
    partition_order = {
        "eligible": 0,
        "audit_blocked": 1,
        "over_cap": 2,
    }
    ordered = sorted(
        candidates,
        key=lambda item: (
            partition_order[item.partition],
            -Decimal(item.objective_probability_decimal),
            item.stake_minor,
            item.content_hash,
        ),
    )
    eligible_rank = 0
    result = []
    for candidate in ordered:
        rank = None
        if candidate.partition == "eligible":
            eligible_rank += 1
            rank = eligible_rank
        result.append(
            CandidateComparison(
                rank=rank,
                partition=candidate.partition,
                deployable=candidate.deployable,
                tickets=candidate.tickets,
                ticket_count=candidate.ticket_count,
                distinct_note_count=candidate.distinct_note_count,
                paid_note_unit_count=candidate.paid_note_unit_count,
                stake_minor=candidate.stake_minor,
                cap_utilization_decimal=candidate.cap_utilization_decimal,
                probability_kind=candidate.probability_kind,
                objective_label=candidate.objective_label,
                objective_probability_decimal=candidate.objective_probability_decimal,
                expected_broken_legs_decimal=candidate.expected_broken_legs_decimal,
                common_dead_faces=candidate.common_dead_faces,
                break_even_bonus_minor=candidate.break_even_bonus_minor,
                break_even_to_median_decimal=candidate.break_even_to_median_decimal,
                audit_findings=candidate.audit_findings,
                content_hash=candidate.content_hash,
                odds_band=candidate.odds_band,
                target_odds_min_decimal=candidate.target_odds_min_decimal,
                target_odds_max_decimal=candidate.target_odds_max_decimal,
                combined_decimal_odds=candidate.combined_decimal_odds,
                parent_candidate_revision_id=candidate.parent_candidate_revision_id,
                delta_reason=candidate.delta_reason,
            )
        )
    return tuple(result)


__all__ = [
    "BandCandidateGenerationResult",
    "CandidateAuditFinding",
    "CandidateBandResult",
    "CandidateComparison",
    "CandidateGenerationInput",
    "CandidateGenerationResult",
    "CandidateSpaceLimitError",
    "CandidateStructureTemplate",
    "CandidateTicket",
    "CandidateTicketLeg",
    "FaceBundleOption",
    "OfferCandidateInput",
    "ODDS_BAND_INTERVALS",
    "enumerate_band_candidates",
    "enumerate_candidates",
    "union_probability",
]
