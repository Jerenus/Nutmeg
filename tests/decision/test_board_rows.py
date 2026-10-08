import json
from pathlib import Path

from nutmeg.decision.board_rows import fmt_stance, jczq_rows

DAY = "2026-10-06"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_jczq_rows_pairs_every_input_by_code_and_match_id(tmp_path: Path):
    day = tmp_path / "jczq" / "daily" / DAY
    _write(day / "jczq-legs-base.json", {"legs": {
        "周二002": {"match_id": "m2", "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}},
        "周二001": {"match_id": "m1", "fair": {"home": 0.4, "draw": 0.3, "away": 0.3}}}})
    _write(day / "reads.json", [{"match_id": "m1", "belief": {"home": 0.45}}, "junk"])
    _write(day / "closing_odds.json", {"周二002": {"book_count": 9}})
    _write(day / "price-band-周二001.json", {"drift_pp": {"home": 1.0}})
    _write(day / "research-周二001.json", {"summary": "s"})
    _write(day / "research-周二002.json", ["old", "format"])
    rows = jczq_rows(tmp_path, DAY)
    assert [r["code"] for r in rows] == ["周二002", "周二001"]            # legs-base 原顺序
    by = {r["code"]: r for r in rows}
    assert by["周二001"]["read"] == {"match_id": "m1", "belief": {"home": 0.45}}
    assert by["周二002"]["read"] == {} and by["周二002"]["closing"] == {"book_count": 9}
    assert by["周二001"]["band"] == {"drift_pp": {"home": 1.0}} and by["周二002"]["band"] == {}
    assert by["周二001"]["research"] == {"summary": "s"} and by["周二002"]["research"] is None
    assert jczq_rows(tmp_path, "2026-10-07") == []                        # 无板 = 空
    only = jczq_rows(tmp_path, DAY, legs={"周二009": {"match_id": "m9", "fair": {}}})
    assert [r["code"] for r in only] == ["周二009"]


def test_fmt_stance_keeps_each_surface_empty_label():
    assert fmt_stance({"face": "3", "faces": "31"}) == "押3·31"
    assert fmt_stance({"face": "0"}) == "押0·0"
    assert fmt_stance(None) == "—" and fmt_stance({}, empty="未表态") == "未表态"
