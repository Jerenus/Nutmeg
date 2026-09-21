"""Closed, externally reviewed structural control scope (no shipped approval)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import FrozenContract
from nutmeg.ontology.discovery.models import canonical_hash


class ScopeBinding(FrozenContract):
    pilot: Literal["structural"]
    board: str = Field(min_length=1)


class PilotScopeContract(FrozenContract):
    schema_version: Literal["1"]
    pilot_id: Literal["structural-candidate-v1"]
    family: Literal["structural_candidate_exploration"]
    task_family: Literal["structural_candidate_audit"]
    mode: Literal["scoped_control"]
    scope: ScopeBinding
    operators: tuple[Literal["enumerate_template_shard", "stop"], ...]
    effective_boundary: str
    exposure_cap: int = Field(ge=1)
    fallback_policy_revision_id: str = Field(min_length=1)
    no_ticket_fallback: Literal[True]
    brake_codes: tuple[Literal[
        "permission_leak", "audit_invalidation", "protected_mutation",
        "resource_overrun", "manifest_breach",
    ], ...]
    approval_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def closed_surface(self):
        if (not self.operators
            or len(set(self.operators)) != len(self.operators)
            or not self.brake_codes or len(set(self.brake_codes)) != len(self.brake_codes)
            or datetime.fromisoformat(self.effective_boundary).tzinfo is None):
            raise ValueError("invalid structural control scope")
        return self


def validate_control_scope(scope: dict, pilot_contract: dict, *, reviewed_hash: str | None = None,
                           approval_ref: str | None = None) -> PilotScopeContract:
    if not reviewed_hash or not approval_ref:
        raise ValueError("reviewed prospective scope contract is required for control")
    try:
        contract = PilotScopeContract.model_validate(pilot_contract)
    except (ValueError, TypeError) as exc:
        raise ValueError("reviewed prospective scope contract is required for control") from exc
    if (canonical_hash(contract.model_dump(mode="json")) != reviewed_hash
        or contract.approval_ref != approval_ref or contract.scope.model_dump() != scope):
        raise ValueError("reviewed prospective scope contract hash/scope mismatch")
    return contract
