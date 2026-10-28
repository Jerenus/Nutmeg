from nutmeg.decision.choice_ledger import shape_of


def test_shape_of_counts_singles_doubles_triples():
    assert shape_of({"13": "3", "8": "3", "2": "31", "4": "10", "1": "310"}) == "2单2双1包"
    assert shape_of({}) == "—"
