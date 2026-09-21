import json
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.iteration_contract import IterationContract, load_iteration_contract

ROOT = Path(__file__).resolve().parents[2] / "experiments/discovery"


def test_proposed_contract_is_strict_frozen_and_binds_d0():
    pilot = load_pilot_contract(ROOT / "structural-candidate-v1.contract.json")
    contract = load_iteration_contract(ROOT / "structural-iteration-v1.contract.json", pilot)
    assert contract.approval_status == "proposed_unapproved"
    assert contract.duplicate_cluster_key == pilot.readiness.duplicate_cluster_key
    assert contract.archive_capacity == pilot.archive.capacity
    assert contract.holdout_rotation == "sealed_strictly_newer_unexposed_cluster"
    with pytest.raises(ValueError):
        contract.min_effective_new_clusters = 0


@pytest.mark.parametrize(
    "change",
    [
        {"min_effective_new_clusters": 0},
        {"approval_status": "approved"},
        {"auto_create_tournament": True},
        {"duplicate_cluster_key": ["world_id"]},
        {"archive_capacity": 13},
        {"holdout_rotation": "calendar_date_only"},
        {"unexpected": "field"},
    ],
)
def test_proposed_contract_rejects_unsafe_mutations(change):
    pilot = load_pilot_contract(ROOT / "structural-candidate-v1.contract.json")
    document = json.loads((ROOT / "structural-iteration-v1.contract.json").read_text())
    document.update(change)
    with pytest.raises(ValueError):
        IterationContract.model_validate_with_pilot(document, pilot)
