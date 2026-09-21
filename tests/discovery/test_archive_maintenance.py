import pytest

from nutmeg.discovery.archive_maintenance import ArchivePolicy, propose_archive


def policy(name, actions, *, lineage="a", eligible=True, parent_registered=True):
    return ArchivePolicy(name, lineage, frozenset(actions), eligible, parent_registered)


def test_full_archive_evicts_dominated_clone_before_unique_stepping_stone():
    existing = tuple(policy(f"p{i}", {f"action{i}"}, lineage=f"l{i}") for i in range(11)) + (
        policy("clone", {"new"}, lineage="other"),
    )
    proposal = propose_archive(existing, (policy("new", {"new", "useful"}),), winner_id="incumbent")
    assert proposal.admit_ids == ("new",)
    assert proposal.evict_ids == ("clone",)
    assert proposal.winner_id == "incumbent"


def test_rejects_disqualified_and_lineage_cap():
    existing = tuple(policy(f"p{i}", {f"a{i}"}) for i in range(3))
    with pytest.raises(ValueError, match="eligible"):
        propose_archive(
            existing, (policy("bad", {"unique"}, eligible=False),), winner_id="incumbent"
        )
    with pytest.raises(ValueError, match="lineage"):
        propose_archive(existing, (policy("fourth", {"unique"}),), winner_id="incumbent")
    with pytest.raises(ValueError, match="registered parent"):
        propose_archive(
            (), (policy("orphan", {"unique"}, parent_registered=False),), winner_id="incumbent"
        )


def test_rejects_winner_as_stepping_stone_and_duplicate_distance():
    with pytest.raises(ValueError, match="winner"):
        propose_archive((), (policy("incumbent", {"a"}),), winner_id="incumbent")
    with pytest.raises(ValueError, match="distance"):
        propose_archive(
            (policy("prior", {"a"}),), (policy("same", {"a"}, lineage="b"),), winner_id="incumbent"
        )


def test_archive_caller_cannot_override_d0_capacity():
    with pytest.raises(TypeError, match="capacity"):
        propose_archive((), (), winner_id="incumbent", capacity=999)
