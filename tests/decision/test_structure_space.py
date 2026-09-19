import pytest

from nutmeg.decision.structure_space import (
    NoFaceStatusError,
    cover_options,
    enumerate_frontier,
    frontier_hash,
)

LQ4 = {
    "q1_spine": True,
    "q2_route": True,
    "q3a_opponent_scores": False,
    "q4_no_context_flag": True,
}
LQ3 = {**LQ4, "q4_no_context_flag": False}


def _leg(fair, *, lq=LQ4, integrity="pass", d3=None, dead=()):
    d3 = d3 or {}
    face_status = {
        face: {
            "state": "dead" if face in dead else "alive",
            "proofs": {},
            "precedent": "none",
            "source": "x",
        }
        for face in ("home", "draw", "away")
    }
    return {
        "license_questions": lq,
        "anchor_integrity": integrity,
        "crash_markers": [],
        "fair": dict(zip(("home", "draw", "away"), fair, strict=True)),
        "_d3": {
            face: {"a": count >= 1, "b": count >= 2, "c": count >= 3}
            for face, count in d3.items()
        },
        "face_status": face_status,
    }


def test_t3_match_only_offers_full_cover_and_t1_narrows_only_cheap_proven_faces():
    t3 = _leg((0.4, 0.3, 0.3), lq=LQ3, integrity="fail")
    assert cover_options(t3, mode="matrix") == [("310", 1.0)]
    t1 = _leg((0.6, 0.25, 0.15), d3={"away": 2, "draw": 2})
    assert {faces for faces, _ in cover_options(t1, mode="matrix")} == {"310", "31"}
    assert {faces for faces, _ in cover_options(t1, mode="strict")} == {"310"}


def test_dead_face_is_never_covered_in_either_mode():
    leg = _leg((0.6, 0.25, 0.15), dead=("away",))
    assert {faces for faces, _ in cover_options(leg, mode="strict")} == {"31"}
    assert "310" not in {faces for faces, _ in cover_options(leg, mode="matrix")}


def test_frontier_is_deterministic_bounded_by_cap_and_reports_shape():
    legs = {
        str(i): _leg((0.6, 0.25, 0.15), d3={"away": 2}, dead=("draw",))
        for i in range(1, 15)
    }
    frontier = enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")
    assert frontier["max_p"] is not None
    assert all(point["stake_yuan"] <= 400 for point in frontier["points"])
    assert all(
        set(point["shape"]) == {"singles", "doubles", "fulls"}
        for point in frontier["points"]
    )
    assert all(
        narrowing["excluded_face"] == "away"
        for point in frontier["points"]
        for narrowing in point["narrowings"]
    )
    again = enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")
    assert frontier["frontier_hash"] == again["frontier_hash"]
    assert (
        frontier_hash(legs, channel="renjiu", cap_yuan=400, mode="matrix")
        == frontier["frontier_hash"]
    )


def test_frontier_respects_the_ticket_level_narrowing_cap():
    legs = {
        str(i): _leg(
            (0.14, 0.14, 0.72),
            d3={"home": 2, "draw": 2},
            dead=("away",),
        )
        for i in range(1, 15)
    }
    for cap in (400, 1200):
        frontier = enumerate_frontier(legs, channel="renjiu", cap_yuan=cap, mode="matrix")
        assert frontier["points"], f"cap={cap} should not have an empty frontier"
        assert max(len(point["narrowings"]) for point in frontier["points"]) <= 3


def test_shengfucai_covers_all_fourteen_and_empty_frontier_is_none_not_error():
    legs = {
        str(i): _leg((0.4, 0.3, 0.3), lq=LQ3, integrity="fail") for i in range(1, 15)
    }
    frontier = enumerate_frontier(legs, channel="shengfucai", cap_yuan=400, mode="matrix")
    assert frontier["max_p"] is None and frontier["points"] == []
    large = enumerate_frontier(
        legs, channel="shengfucai", cap_yuan=3**14 * 2, mode="matrix"
    )
    assert len(large["points"]) == 1 and large["points"][0]["notes"] == 3**14


def test_refuses_legs_without_face_status():
    legs = {"1": {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}}
    with pytest.raises(NoFaceStatusError):
        enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")


def test_third_order_sort_key_prefers_full_cover_on_lowest_top1_among_equal_p():
    from nutmeg.decision.structure_space import third_order_key

    a = {
        "p_all": 0.10,
        "chosen": (("1", "310"), ("2", "3")),
        "top1": {"1": 0.40, "2": 0.70},
    }
    b = {
        "p_all": 0.10,
        "chosen": (("1", "3"), ("2", "310")),
        "top1": {"1": 0.40, "2": 0.70},
    }
    assert third_order_key(a) < third_order_key(b)
