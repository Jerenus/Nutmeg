"""D7 information/drift thresholds.

The artifact starts `proposed_unapproved`. Only a human approval recorded inside the
artifact itself, bound to the canonical hash of the proposed numbers, flips it to
`approved`. Neither state grants runtime authority; approval only removes the
`contract_unapproved` trigger block.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import FrozenContract, PilotContract, canonical_hash
from nutmeg.ontology.discovery.models import canonical_hash as canonical_hash_document


class IterationContract(FrozenContract):
    schema_version: Literal["1"]
    contract_id: Literal["structural-iteration-v1"]
    approval_status: Literal["proposed_unapproved", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    approval_ref: str | None = None
    approves_proposed_hash: str | None = None
    duplicate_cluster_key: tuple[str, ...]
    holdout_rotation: Literal["sealed_strictly_newer_unexposed_cluster"]
    archive_capacity: int = Field(ge=1)
    max_per_lineage: int = Field(ge=1)
    minimum_action_jaccard_distance: float = Field(ge=0, le=1)
    min_effective_new_clusters: int = Field(ge=1)
    min_days_between_rounds: int = Field(ge=0)
    min_action_coverage_delta: int = Field(ge=0)
    min_failure_case_delta: int = Field(ge=0)
    min_stratum_count_delta: int = Field(ge=0)
    min_drift_sample_clusters: int = Field(ge=1)
    min_material_quality_gain: float = Field(gt=0)
    max_branch_growth_without_gain: float = Field(ge=0)
    worst_stratum_max_decline: float = Field(ge=0)
    hard_invariant_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_hard_invariants(self) -> IterationContract:
        if not self.hard_invariant_codes or len(set(self.hard_invariant_codes)) != len(
            self.hard_invariant_codes
        ):
            raise ValueError("registered hard invariant codes are required")
        return self

    @model_validator(mode="after")
    def validate_approval(self) -> IterationContract:
        approval = (
            self.approved_by,
            self.approved_at,
            self.approval_ref,
            self.approves_proposed_hash,
        )
        if self.approval_status == "proposed_unapproved":
            if any(value is not None for value in approval):
                raise ValueError("an unapproved contract cannot carry approval fields")
            return self
        if any(value is None or not str(value).strip() for value in approval):
            raise ValueError(
                "approval requires approved_by, approved_at, approval_ref and "
                "approves_proposed_hash"
            )
        if datetime.fromisoformat(str(self.approved_at)).tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        if self.approves_proposed_hash != proposed_contract_hash(self):
            raise ValueError("approval hash does not match the proposed numbers")
        return self

    def proposed_form(self) -> IterationContract:
        """The same numbers with every approval field stripped."""
        return self.model_copy(
            update={
                "approval_status": "proposed_unapproved",
                "approved_by": None,
                "approved_at": None,
                "approval_ref": None,
                "approves_proposed_hash": None,
            }
        )

    @property
    def approved(self) -> bool:
        return self.approval_status == "approved"

    @classmethod
    def model_validate_with_pilot(cls, document: object, pilot: PilotContract) -> IterationContract:
        contract = cls.model_validate(document)
        if (
            contract.duplicate_cluster_key != pilot.readiness.duplicate_cluster_key
            or contract.archive_capacity != pilot.archive.capacity
            or contract.max_per_lineage != pilot.archive.max_per_lineage
            or contract.minimum_action_jaccard_distance
            != pilot.archive.minimum_action_jaccard_distance
        ):
            raise ValueError("iteration contract must preserve frozen D0 guards")
        return contract


def load_iteration_contract(path: Path, pilot: PilotContract) -> IterationContract:
    return IterationContract.model_validate_with_pilot(
        json.loads(path.read_text(encoding="utf-8")), pilot
    )


def proposed_contract_hash(contract: IterationContract) -> str:
    """Hash of the proposed numbers only; identical before and after approval."""
    payload = contract.proposed_form().model_dump(mode="json", exclude_none=True)
    return canonical_hash_document(payload)


def approved_contract_hash(contract: IterationContract) -> str:
    """Hash of the full artifact including its approval record."""
    return canonical_hash(contract)
