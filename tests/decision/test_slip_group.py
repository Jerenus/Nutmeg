"""多张足彩票一起看的算术（2026-10-09）。

26136 那天这几样全是会话里手写脚本算的：至少中一张、两两同死、给定一场赛果后各票还剩多少、
固定主单搜互补副单。同一推导写了六遍，收成一处。"""
from itertools import combinations, product

from nutmeg.decision.slip_group import best_complement, co_death, given, p_all, p_any

FAIR = {"1": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "2": {"home": 0.6, "draw": 0.25, "away": 0.15}}
A = {"1": "3", "2": "31"}
B = {"1": "31", "2": "3"}


def test_p_all_multiplies_the_faces_every_ticket_shares_per_match():
    assert abs(p_all([A], FAIR) - 0.5 * 0.85) < 1e-12
    assert abs(p_all([A, B], FAIR) - 0.5 * 0.6) < 1e-12     # 场1 只剩 3，场2 只剩 3


def test_p_any_is_inclusion_exclusion_not_a_sum():
    assert abs(p_any([A, B], FAIR) - (0.425 + 0.48 - 0.30)) < 1e-12


def test_co_death_lists_results_no_ticket_covers_on_matches_all_tickets_play():
    p, points = co_death([A, B], FAIR)
    assert points == [("1", "0", 0.2), ("2", "0", 0.15)]
    assert abs(p - (1 - 0.8 * 0.85)) < 1e-12


def test_given_pins_a_result_so_tickets_without_that_face_drop_to_zero():
    pinned = given(FAIR, {"1": "1"})
    assert p_all([A], pinned) == 0
    assert abs(p_all([B], pinned) - 0.6) < 1e-12


def _brute(base, fair, n_matches, max_notes):
    naked = {(no, f) for t in base for no, f in t.items() if len(f) == 1}
    subsets = ["3", "1", "0", "31", "30", "10", "310"]
    best = 0.0
    for nos in combinations(sorted(fair), n_matches):
        for faces in product(subsets, repeat=n_matches):
            t = dict(zip(nos, faces, strict=True))
            notes = 1
            for f in faces:
                notes *= len(f)
            if notes > max_notes or any((no, f) in naked for no, f in t.items()):
                continue
            best = max(best, p_any([*base, t], fair))
    return best


def test_best_complement_finds_the_brute_force_optimum_on_a_small_board():
    fair = {"1": {"home": 0.62, "draw": 0.22, "away": 0.16},
            "2": {"home": 0.45, "draw": 0.27, "away": 0.28},
            "3": {"home": 0.35, "draw": 0.30, "away": 0.35},
            "4": {"home": 0.72, "draw": 0.17, "away": 0.11}}
    base = [{"1": "3", "2": "31", "4": "3"}]
    found = best_complement(base, fair, n_matches=3, max_notes=4)
    assert found is not None
    score, ticket = found
    assert abs(score - _brute(base, fair, 3, 4)) < 1e-12
    notes = 1
    for f in ticket.values():
        notes *= len(f)
    assert len(ticket) == 3 and notes <= 4
    # 不与基准共享裸单（V2 否决的结构搜出来也没法买）
    assert not any(ticket.get(no) == f for t in base for no, f in t.items() if len(f) == 1)


def test_best_complement_keeps_fixed_faces():
    fair = {str(n): {"home": 0.5, "draw": 0.28, "away": 0.22} for n in range(1, 6)}
    score, ticket = best_complement([{"1": "3", "2": "3", "3": "3"}], fair, n_matches=3,
                                    max_notes=8, fixed={"1": "31"})
    assert ticket["1"] == "31" and score > 0
