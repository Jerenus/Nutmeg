from nutmeg.decision.zucai_night import result_code


def test_result_code_home_win():
    assert result_code(4, 1) == "3"


def test_result_code_draw():
    assert result_code(1, 1) == "1"


def test_result_code_away_win():
    assert result_code(1, 2) == "0"
