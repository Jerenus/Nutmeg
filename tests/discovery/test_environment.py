from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.environment import Continue, ContinueBatch, Observation, Stop, validate_action

PILOT = load_pilot_contract(
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _observation(**changes):
    values = dict(
        world_id="world-1",
        visible_node_ids=("root",),
        frontier_node_ids=("root",),
        selectable_node_ids=(),
        legal_template_ids=("T1", "T2"),
        remaining_rounds=2,
        remaining_nodes=2,
        max_concurrency=2,
    )
    values.update(changes)
    return Observation(**values)


@pytest.mark.parametrize(
    ("action", "error"),
    [
        (Continue("hidden", ("T1",)), "visible frontier"),
        (Continue("root", ("unknown",)), "legal template"),
        (Continue("root", ("T1",), operator="unknown"), "legal operator"),
        (ContinueBatch((Continue("root", ("T1",)),) * 2), "duplicate"),
        (Stop(("hidden",)), "selectable"),
    ],
)
def test_action_rejects_hidden_or_illegal_choices(action, error):
    with pytest.raises(ValueError, match=error):
        validate_action(_observation(), action, PILOT)


def test_action_rejects_exhausted_budget_and_concurrency():
    with pytest.raises(ValueError, match="round budget"):
        validate_action(_observation(remaining_rounds=0), Continue("root", ("T1",)), PILOT)
    with pytest.raises(ValueError, match="node budget"):
        validate_action(_observation(remaining_nodes=0), Continue("root", ("T1",)), PILOT)
    with pytest.raises(ValueError, match="concurrency"):
        validate_action(
            _observation(max_concurrency=1),
            ContinueBatch(
                (
                    Continue("root", ("T1",)),
                    Continue("root", ("T2",)),
                )
            ),
            PILOT,
        )


def test_policy_state_has_version_and_byte_limit():
    from nutmeg.discovery.environment import policy_state_hash

    assert policy_state_hash({"schema_version": "1", "cursor": 1}) == policy_state_hash(
        {"cursor": 1, "schema_version": "1"}
    )
    with pytest.raises(ValueError, match="state"):
        policy_state_hash({"schema_version": "1", "data": "x" * 65536})


def test_replay_and_online_expose_legal_actions_only_from_visible_frontier(tmp_path):
    from nutmeg.discovery.online_recorder import OnlineRecordingEnvironment
    from tests.discovery.test_online_adapter import _snapshot
    from tests.discovery.test_online_recorder import T0, _rig
    from tests.discovery.test_replay_environment import _replay

    replay = _replay()
    replay.reset()
    assert all(
        action.node_id == "node-root"
        for action in replay.legal_actions()
        if isinstance(action, Continue)
    )
    online = OnlineRecordingEnvironment(
        _snapshot(),
        engine=_rig(tmp_path),
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=T0,
        fixture_only=True,
    )
    root = online.reset().visible_node_ids[0]
    assert all(
        action.node_id == root for action in online.legal_actions() if isinstance(action, Continue)
    )
