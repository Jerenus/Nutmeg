import json
from pathlib import Path

from nutmeg.migration.old_store import read_objects


def test_reads_jsonl_rows_and_skips_blanks(tmp_path: Path) -> None:
    decision = tmp_path / "decision"
    decision.mkdir()
    (decision / "matches.jsonl").write_text(
        json.dumps({"match_id": "m1"}) + "\n\n" + json.dumps({"match_id": "m2"}) + "\n",
        encoding="utf-8")
    rows = read_objects(decision, "matches")
    assert [r["match_id"] for r in rows] == ["m1", "m2"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_objects(tmp_path, "reads") == []
