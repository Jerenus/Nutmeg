from nutmeg.ontology.finance.models import SettlementGrade
from nutmeg.ontology.finance.settlement import grade_had


def test_grade_had() -> None:
    assert grade_had("home", 2, 1) is SettlementGrade.WIN
    assert grade_had("away", 2, 1) is SettlementGrade.LOSS
    assert grade_had("draw", 1, 1) is SettlementGrade.WIN
    assert grade_had("home", 1, 1) is SettlementGrade.LOSS
    assert grade_had("away", 0, 3) is SettlementGrade.WIN
