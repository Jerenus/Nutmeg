import json
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.iteration_contract import (
    IterationContract,
    approved_contract_hash,
    load_iteration_contract,
    proposed_contract_hash,
)

ROOT = Path(__file__).resolve().parents[2] / "experiments/discovery"
PROPOSED_HASH = "bda3be2dd7b4545bb0323453346564474c2bfa08e17872349302979f81e8f23b"
APPROVAL_FIELDS = ("approved_by", "approved_at", "approval_ref", "approves_proposed_hash")


def _pilot():
    return load_pilot_contract(ROOT / "structural-candidate-v1.contract.json")


def _document() -> dict:
    return json.loads((ROOT / "structural-iteration-v1.contract.json").read_text())


def _proposed_document() -> dict:
    document = {k: v for k, v in _document().items() if k not in APPROVAL_FIELDS}
    document["approval_status"] = "proposed_unapproved"
    return document


def test_approved_contract_is_strict_frozen_binds_d0_and_proposed_hash():
    pilot = _pilot()
    contract = load_iteration_contract(ROOT / "structural-iteration-v1.contract.json", pilot)
    assert contract.approval_status == "approved"
    assert contract.approved
    assert contract.approves_proposed_hash == PROPOSED_HASH
    assert proposed_contract_hash(contract) == PROPOSED_HASH
    assert approved_contract_hash(contract) != PROPOSED_HASH
    assert contract.duplicate_cluster_key == pilot.readiness.duplicate_cluster_key
    assert contract.archive_capacity == pilot.archive.capacity
    assert contract.holdout_rotation == "sealed_strictly_newer_unexposed_cluster"
    with pytest.raises(ValueError):
        contract.min_effective_new_clusters = 0


def test_proposed_form_reproduces_the_unapproved_d7_hash():
    proposed = IterationContract.model_validate_with_pilot(_proposed_document(), _pilot())
    assert proposed.approval_status == "proposed_unapproved"
    assert not proposed.approved
    assert proposed_contract_hash(proposed) == PROPOSED_HASH


@pytest.mark.parametrize(
    "change",
    [
        {"min_effective_new_clusters": 0},
        {"approval_status": "approved"},
        {"approved_by": "op:jun"},
        {"auto_create_tournament": True},
        {"duplicate_cluster_key": ["world_id"]},
        {"archive_capacity": 13},
        {"holdout_rotation": "calendar_date_only"},
        {"unexpected": "field"},
    ],
)
def test_proposed_contract_rejects_unsafe_mutations(change):
    document = _proposed_document()
    document.update(change)
    with pytest.raises(ValueError):
        IterationContract.model_validate_with_pilot(document, _pilot())


@pytest.mark.parametrize(
    "change",
    [
        {"min_effective_new_clusters": 4},
        {"worst_stratum_max_decline": 0.2},
        {"approves_proposed_hash": "0" * 64},
        {"approved_at": "2026-09-22T12:00:00"},
        {"approved_by": ""},
        {"approval_ref": None},
    ],
)
def test_approved_numbers_cannot_change_without_a_new_approval(change):
    document = _document()
    document.update(change)
    with pytest.raises(ValueError):
        IterationContract.model_validate_with_pilot(document, _pilot())
