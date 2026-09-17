# tests/decision/test_premise_card.py
"""前提卡 —— 派研究前把「我记得的」换成「store 里有的」。"""

from nutmeg.decision.premise_card import (
    UNKNOWN,
    build_card,
    collect_corrections,
    format_cards,
)

MATCH = {"home": "曼彻斯特城", "away": "诺维奇", "competition": "欧联", "kickoff": "03:00"}
FAIR = {"home": 0.847, "draw": 0.099, "away": 0.054}


def _note(key, note, at="2026-09-17"):
    return {"key": key, "note": note, "evidence": "https://example/x", "at": at}


def test_missing_profile_says_so_instead_of_leaving_a_blank():
    """出生事故 26128：我凭记忆填的前提一期错六条（主帅错三个）。
    卡上没有的必须明写「未提供」，不能留白让我顺手补。"""
    card = build_card(MATCH, match_no=11, fair=FAIR, profiles={})
    assert card.unknown_count == 10
    text = card.render()
    assert UNKNOWN in text
    assert "请独立取证" in text


def test_known_premise_carries_tier_and_date():
    card = build_card(
        MATCH, match_no=11, fair=FAIR,
        profiles={"曼彻斯特城": [_note("coach", "Maresca（2026-06-29 接任）")]},
    )
    line = next(line for line in card.home_lines if line.field == "coach")
    assert line.known
    assert "Maresca" in line.render()
    assert "2026-09-17" in line.render()


def test_latest_note_wins_for_the_same_key():
    card = build_card(
        MATCH, match_no=11, fair=FAIR,
        profiles={"曼彻斯特城": [
            _note("coach", "瓜迪奥拉", at="2026-05-01"),
            _note("coach", "Maresca", at="2026-06-29"),
        ]},
    )
    line = next(line for line in card.home_lines if line.field == "coach")
    assert "Maresca" in line.value


def test_both_sides_get_their_own_lines():
    card = build_card(
        MATCH, match_no=11, fair=FAIR,
        profiles={"诺维奇": [_note("league_position", "英冠第 9")]},
    )
    assert all(not line.known for line in card.home_lines)
    assert any(line.known for line in card.away_lines)


def test_card_header_reports_store_coverage():
    cards = [build_card(MATCH, match_no=11, fair=FAIR, profiles={})]
    text = format_cards(cards, issue="26128")
    assert "store 覆盖 0/10 条" in text
    assert "卡上没有的，我不许替 agent 补" in text


# —— 纠正回收 ————————————————————————————————————

def _research(**corrections):
    return {"match_no": 11, "premise_corrections": [corrections]}


def test_correction_without_evidence_is_refused():
    """纠正也是证据；无出处的纠正只是换一个人的记忆。"""
    assert collect_corrections(
        _research(subject="曼彻斯特城", field="coach", correct="Maresca")
    ) == []


def test_correction_without_a_subject_is_refused():
    assert collect_corrections(
        _research(field="coach", correct="Maresca", evidence="https://x")
    ) == []


def test_well_formed_correction_is_collected():
    found = collect_corrections(_research(
        subject="曼彻斯特城", field="coach", given="瓜迪奥拉",
        correct="Maresca", evidence="https://mancity/news", as_of="2026-06-29",
    ))
    assert len(found) == 1
    assert found[0].match_no == 11
    assert found[0].subject_type == "team"
    assert "瓜迪奥拉" in found[0].render()
    assert "Maresca" in found[0].render()


def test_league_subject_type_is_preserved():
    found = collect_corrections(_research(
        subject="英冠", subject_type="league", field="note",
        correct="考文垂本季在英超", evidence="https://x",
    ))
    assert found[0].subject_type == "league"


def test_missing_corrections_field_is_not_an_error():
    assert collect_corrections({"match_no": 11}) == []
    assert collect_corrections({"match_no": 11, "premise_corrections": "文字"}) == []
