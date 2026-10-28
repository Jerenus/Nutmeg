from nutmeg.decision.betslip import format_faces_row, parse_faces_row

_ROW = "310 10 0 3 310 31 30 * 1 * * * 3 *"


def test_format_is_inverse_of_parse():
    assert format_faces_row(parse_faces_row(_ROW)) == _ROW


def test_format_normalises_face_order_and_marks_unpicked():
    assert format_faces_row({"2": "13", "14": "0"}) == "* 31 * * * * * * * * * * * 0"
