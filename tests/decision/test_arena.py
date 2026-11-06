"""竞彩虚拟规则赛：选腿、结算、地板、账本、冻结、榜单。"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from nutmeg.decision.arena.backtest import Day, check_admission, dev_pack, history_days, replay
from nutmeg.decision.arena.baseline import baseline_rules
from nutmeg.decision.arena.board import champion_line, render_board, track_rows
from nutmeg.decision.arena.floor import floor_tickets
from nutmeg.decision.arena.freeze import freeze_day
from nutmeg.decision.arena.ledger import (
    add_rule,
    append_jsonl,
    arena_dir,
    load_rules,
    read_jsonl,
)
from nutmeg.decision.arena.legs import build_legs
from nutmeg.decision.arena.rules import pick_legs, validate_rule
from nutmeg.decision.arena.settle import settle_pending, settle_ticket
from nutmeg.decision.bj_time import BJ


def _row(code, line="-1", had=("1.50", "4.00", "6.00"), hh=("2.60", "3.40", "2.10"),
         date="2026-11-07", time="03:00", league="英超"):
    h, d, a = had
    x, y, z = hh
    return {"matchNumStr": code, "businessDate": "2026-11-06", "matchStatus": "Selling",
            "matchDate": date, "matchTime": time, "leagueAbbName": league,
            "homeTeamAbbName": f"主{code}", "awayTeamAbbName": f"客{code}",
            "had": {"h": h, "d": d, "a": a},
            "hhad": {"h": x, "d": y, "a": z, "goalLine": line}}


def _value(*rows):
    return {"matchInfoList": [{"businessDate": "2026-11-06", "subMatchList": list(rows)}]}


FAIR = {"match_winner": {"fair_probability": {"home": 0.6, "draw": 0.25, "away": 0.15}}}
REF = datetime(2026, 11, 6, 18, 40, tzinfo=BJ)


def _leg(code, sp=2.0, p=0.5, **kw):
    leg = {"code": code, "name": code, "market": "had", "face": "home", "line": None, "sp": sp,
           "p_fair": p, "ret": sp * p, "gap": 0.0, "is_fav": True, "is_dog": False,
           "stance_match": False, "league_group": "other", "weekday": 4,
           "hours_to_kickoff": 8.0, "kickoff": "2026-11-07T03:00:00+08:00"}
    return leg | kw


def _rule(**kw):
    rule = {"id": "T-1", "tier": [10, 20], "filter": {"market": ["had"]}, "score": "ret",
            "legs": [2, 5], "mechanism": "机制", "falsify": "证伪"}
    return rule | kw


def _ticket(legs, frozen="2026-11-06T18:40:00+08:00", first="2026-11-07T03:00:00+08:00"):
    return {"ticket_id": "t", "day": "2026-11-06", "stake": 10, "frozen_at": frozen,
            "first_kickoff": first, "legs": legs}


# --- 候选腿 ---------------------------------------------------------------
def test_minus_one_line_gives_not_win_leg_with_summed_fair():
    legs = build_legs(_value(_row("周五001")), {"周五001": FAIR}, "2026-11-06", ref=REF)
    assert {x["face"] for x in legs} == {"home", "draw", "away", "not_win"}
    leg = next(x for x in legs if x["face"] == "not_win")
    assert leg["sp"] == 2.10 and leg["p_fair"] == pytest.approx(0.40)
    assert leg["ret"] == pytest.approx(0.84)
    assert leg["hours_to_kickoff"] == pytest.approx(8.333, abs=0.01)


def test_plus_one_line_gives_not_lose_and_other_lines_give_nothing():
    plus = build_legs(_value(_row("周五001", line="1")), {"周五001": FAIR}, "2026-11-06", ref=REF)
    assert next(x for x in plus if x["face"] == "not_lose")["sp"] == 2.60
    other = build_legs(_value(_row("周五001", line="-2")), {"周五001": FAIR}, "2026-11-06", ref=REF)
    assert {x["market"] for x in other} == {"had"}


def test_match_without_fair_is_skipped_and_gap_uses_devigged_home():
    value = _value(_row("周五001"), _row("周五002"))
    legs = build_legs(value, {"周五001": FAIR}, "2026-11-06", ref=REF)
    assert {x["code"] for x in legs} == {"周五001"}
    home = next(x for x in legs if x["face"] == "home")
    inv = [1 / 1.5, 1 / 4.0, 1 / 6.0]
    assert home["gap"] == pytest.approx(inv[0] / sum(inv) - 0.6)
    assert home["is_fav"] and home["league_group"] == "top5" and home["weekday"] == 4


def test_stance_marks_only_the_matching_had_face():
    legs = build_legs(_value(_row("周五001")), {"周五001": FAIR}, "2026-11-06", ref=REF,
                      stances={"周五001": "1"})
    assert [x["face"] for x in legs if x["stance_match"]] == ["draw"]


# --- 规则 -----------------------------------------------------------------
def test_validate_rejects_post_match_field_and_unknown_tier():
    errors = validate_rule(_rule(filter={"ft_home": [0, 9]}, tier=[10, 30]))
    assert any("ft_home" in e for e in errors) and any("tier" in e for e in errors)
    assert validate_rule(_rule()) == []


def test_validate_requires_mechanism_falsify_and_leg_range():
    assert validate_rule(_rule(mechanism="", legs=[1, 6]))


def test_pick_keeps_matches_distinct_and_tier_left_closed():
    legs = [_leg("A", 2.5, .4), _leg("A", 2.0, .5, face="draw"), _leg("B", 4.0, .25)]
    assert pick_legs(legs, _rule()) == [legs[0], legs[2]]      # 2.5×4＝10，含下界
    assert pick_legs(legs, _rule(tier=[20, 50])) is None
    assert pick_legs([_leg("A", 4.0, .3), _leg("B", 5.0, .3)], _rule()) is None  # 20 不含上界


def test_pick_prefers_highest_joint_probability():
    legs = [_leg("A", 3.0, .3), _leg("B", 4.0, .3), _leg("C", 3.5, .29), _leg("D", 3.2, .32)]
    picked = pick_legs(legs, _rule())
    assert {x["code"] for x in picked} == {"A", "D"} or {x["code"] for x in picked} == {"B", "D"}
    assert pick_legs(list(reversed(legs)), _rule()) == picked


def test_range_and_bool_filters_apply():
    legs = [_leg("A", 3.0, .3, is_fav=False), _leg("B", 4.0, .3), _leg("C", 4.0, .3, is_fav=False)]
    picked = pick_legs(legs, _rule(filter={"is_fav": False, "sp": [2.0, 3.5]}))
    assert picked is None
    assert pick_legs(legs, _rule(filter={"is_fav": False})) == [legs[0], legs[2]]


# --- 结算 -----------------------------------------------------------------
OUT = {"A": {"goals_h": 2, "goals_a": 0}, "B": {"goals_h": 1, "goals_a": 1}}


def test_settle_win_loss_and_void():
    win = [_leg("A", 2.0), _leg("B", 5.0, face="not_win", market="hhad", line=-1.0)]
    done = settle_ticket(_ticket(win), OUT, set(), "now")
    assert done["status"] == "won" and done["payout"] == 100.0 and done["pnl"] == 90.0
    lost = [_leg("A", 2.0), _leg("B", 5.0, face="home")]
    assert settle_ticket(_ticket(lost), OUT, set(), "now")["status"] == "lost"
    void = [_leg("A", 2.0), _leg("C", 5.0)]
    assert settle_ticket(_ticket(void), OUT, {"C"}, "now")["payout"] == 20.0


def test_not_lose_leg_wins_on_draw_and_missing_result_stays_pending():
    legs = [_leg("B", 2.0, face="not_lose", market="hhad", line=1.0), _leg("C", 5.0)]
    assert settle_ticket(_ticket(legs), OUT, set(), "now") is None
    legs[1] = _leg("A", 5.0)
    assert settle_ticket(_ticket(legs), OUT, set(), "now")["status"] == "won"


def test_ticket_frozen_after_kickoff_is_rejected():
    done = settle_ticket(_ticket([_leg("A")], frozen="2026-11-07T03:00:00+08:00"), OUT, set(), "n")
    assert done["status"] == "rejected" and done["payout"] is None


# --- 地板 -----------------------------------------------------------------
def test_floor_is_reproducible_in_tier_and_distinct():
    legs = [_leg(f"M{i}", 2.0 + i / 10) for i in range(8)]
    one = floor_tickets("2026-11-06", legs, [10, 20], n=30)
    assert one == floor_tickets("2026-11-06", legs, [10, 20], n=30) and len(one) == 30
    for ticket in one:
        assert 10 <= ticket["odds"] < 20
        codes = [x["code"] for x in ticket["legs"]]
        assert len(set(codes)) == len(codes)
    assert one != floor_tickets("2026-11-07", legs, [10, 20], n=30)


def test_floor_with_too_few_matches_is_empty():
    assert floor_tickets("2026-11-06", [_leg("A")], [10, 20]) == []


# --- 基线与账本 -----------------------------------------------------------
def test_baseline_has_22_valid_tracks_without_dropped_cells():
    rules = baseline_rules()
    assert len(rules) == 22 and len({r["id"] for r in rules}) == 22
    assert all(validate_rule(r) == [] for r in rules)
    ids = {r["id"] for r in rules}
    assert "B-稳胆串-50" not in ids and "B-冷门串-50" not in ids and "R-研究同向-50" in ids


def test_ledger_round_trip_and_rule_cap(tmp_path):
    append_jsonl(arena_dir(tmp_path) / "tickets.jsonl", {"a": 1})
    assert read_jsonl(arena_dir(tmp_path) / "tickets.jsonl") == [{"a": 1}]
    add_rule(tmp_path, "S1", _rule())
    with pytest.raises(ValueError, match="已存在"):
        add_rule(tmp_path, "S1", _rule())
    assert [r["season"] for r in load_rules(tmp_path)] == ["S1"]
    for i in range(39):
        add_rule(tmp_path, "S1", _rule(id=f"T-{i + 2}"))
    with pytest.raises(ValueError, match="上限"):
        add_rule(tmp_path, "S1", _rule(id="T-99"))


# --- 回测与入赛 -----------------------------------------------------------
def _seed_history(root):
    daily = root / "jczq" / "daily"
    results = {}
    for day in ("2026-09-15", "2026-09-16"):
        (daily / day).mkdir(parents=True)
        rows = [_row("周五001"), _row("周五002")]
        for r in rows:
            r["businessDate"] = day
        doc = {"lastUpdateTime": f"{day} 21:50:00",
               "matchInfoList": [{"businessDate": day, "subMatchList": rows}]}
        (daily / day / "sporttery_markets.json").write_text(json.dumps(doc), "utf-8")
        odds = {"周五001": FAIR, "周五002": FAIR}
        (daily / day / "bold_odds.json").write_text(json.dumps(odds), "utf-8")
        results[day] = {"周五001": {"ft_home": 2, "ft_away": 0},
                        "周五002": {"ft_home": 2, "ft_away": 0}}
    (root / "jczq" / "jc-results.json").write_text(json.dumps(results), "utf-8")


def test_history_window_and_replay(tmp_path):
    _seed_history(tmp_path)
    days = history_days(tmp_path, "2026-05-19", "2026-09-15")
    assert [d.day for d in days] == ["2026-09-15"]
    assert len(days[0].legs) == 8 and days[0].outcomes["周五001"]["goals_h"] == 2
    rule = _rule(filter={"face": ["home", "away", "draw"], "sp": [3.0, 7.0]}, tier=[10, 50])
    assert replay(rule, days)
    assert replay(_rule(tier=[50, 100]), days) == []


def test_dev_pack_never_contains_sealed_days(tmp_path):
    _seed_history(tmp_path)
    out = dev_pack(tmp_path, tmp_path / "pack")
    pack = json.loads(out.read_text("utf-8"))
    assert list(pack["days"]) == ["2026-09-15"]


def test_admission_needs_tickets_and_floor():
    leg = [_leg("A", 3.0), _leg("B", 4.0)]
    days = [Day(f"2026-09-{i:02d}", leg, {"A": {"goals_h": 1, "goals_a": 0},
                                         "B": {"goals_h": 1, "goals_a": 0}}, set())
            for i in range(16, 30)]
    verdict = check_admission(_rule(tier=[10, 20]), days)
    assert verdict["tickets"] == 14 and verdict["admitted"] is False and "15" in verdict["reason"]


# --- 冻结 -----------------------------------------------------------------
def _freeze(tmp, now=REF):
    value = _value(_row("周五001", had=("3.00", "3.20", "2.40")),
                   _row("周五002", had=("3.00", "3.20", "2.40")),
                   _row("周五003", had=("3.00", "3.20", "2.40"), date="2026-11-06", time="19:00"))
    odds = {c: FAIR for c in ("周五001", "周五002", "周五003")}
    return freeze_day(tmp, "2026-11-06", value, odds, now=now, source="test")


def test_freeze_writes_once_and_skips_near_kickoff(tmp_path):
    add_rule(tmp_path, "S1", _rule(filter={"face": ["draw"]}))
    first = _freeze(tmp_path)
    assert first["status"] == "frozen" and first["candidates"] == 2 and first["tickets"] == 1
    tickets = read_jsonl(arena_dir(tmp_path) / "tickets.jsonl")
    assert {x["code"] for x in tickets[0]["legs"]} == {"周五001", "周五002"}
    assert tickets[0]["ticket_id"] == "2026-11-06:T-1" and tickets[0]["season"] == "S1"
    assert (arena_dir(tmp_path) / "floor" / "2026-11-06.json").is_file()
    assert _freeze(tmp_path)["status"] == "already"
    assert len(read_jsonl(arena_dir(tmp_path) / "tickets.jsonl")) == 1


def test_freeze_records_empty_track(tmp_path):
    add_rule(tmp_path, "S1", _rule(tier=[50, 100], filter={"face": ["home"], "sp": [1.0, 1.1]}))
    done = _freeze(tmp_path)
    assert done["tickets"] == 0 and done["empty"] == ["T-1"]


def test_settle_pending_appends_once(tmp_path):
    add_rule(tmp_path, "S1", _rule(filter={"face": ["draw"]}))
    _freeze(tmp_path)
    results = {"2026-11-06": {"周五001": {"ft_home": 0, "ft_away": 1},
                              "周五002": {"ft_home": 0, "ft_away": 1}}}
    (tmp_path / "jczq" / "jc-results.json").write_text(json.dumps(results), "utf-8")
    assert settle_pending(tmp_path, "2026-11-07T09:50:00+08:00")["settled"] == 1
    assert settle_pending(tmp_path, "2026-11-07T15:50:00+08:00")["settled"] == 0
    assert len(read_jsonl(arena_dir(tmp_path) / "settled.jsonl")) == 1


# --- 榜单 -----------------------------------------------------------------
def test_track_rows_subtract_same_day_floor():
    entries = {"T-1": [{"day": "d1", "tier": "10-20", "gross": 15.0},
                       {"day": "d2", "tier": "10-20", "gross": 0.0}]}
    floors = {("d1", "10-20"): [0.0, 2.0], ("d2", "10-20"): [1.0, 1.0]}
    row = track_rows(entries, floors)[0]
    assert row["tickets"] == 2 and row["won"] == 1 and row["roi"] == pytest.approx(6.5)
    assert row["score"] == pytest.approx(6.5)


def test_champion_line_is_reproducible_and_board_reports_no_champion():
    floors = {("d1", "10-20"): [0.0, 0.0, 12.0], ("d2", "10-20"): [0.0, 0.0, 15.0]}
    tracks = [("10-20", ["d1", "d2"])] * 3
    line = champion_line(tracks, floors, sims=200)
    assert line == champion_line(tracks, floors, sims=200) and line > 0
    rows = [{"track": "T-1", "tier": "10-20", "tickets": 2, "won": 0, "roi": -1.0,
             "floor_roi": 3.0, "score": -4.0}]
    text = render_board("2026-11", rows, line, pending=3, empty_days=1)
    assert "本季无有效冠军" in text and "T-1" in text and "待结 3" in text
