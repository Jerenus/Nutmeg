from __future__ import annotations

from pathlib import Path

from nutmeg.data.european_odds import CrossCheckSignal
from nutmeg.services.jczq_conflict_store import ConflictStore


def _sig(match_no: str, pick: str = "胜", delta: float = 0.04) -> CrossCheckSignal:
    return CrossCheckSignal(
        match_no=match_no,
        pool="had",
        pick=pick,
        sporttery_implied=0.32,
        european_implied=0.40,
        dispersion=0.08,
        delta=delta,
    )


def test_record_appends_stable_schema_rows(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record(
        "2026-05-16",
        [_sig("周六001"), _sig("周六007", pick="负")],
        sporttery_odds={"周六001": 3.10, "周六007": 2.50},
    )
    rows = store.load()
    assert len(rows) == 2
    first = rows[0]
    assert set(first) == {
        "date",
        "match_no",
        "pool",
        "pick",
        "edge",
        "sporttery_odds",
        "hit",
        "realized_return",
    }
    assert first["date"] == "2026-05-16"
    assert first["match_no"] == "周六001"
    assert first["pool"] == "had"
    assert first["pick"] == "胜"
    assert abs(first["edge"] - 0.04) < 1e-9
    assert abs(first["sporttery_odds"] - 3.10) < 1e-9
    assert first["hit"] is None
    assert first["realized_return"] is None


def test_record_is_additive_across_calls(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.record("2026-05-17", [_sig("周日002")], sporttery_odds={"周日002": 2.00})
    rows = store.load()
    assert [row["date"] for row in rows] == ["2026-05-16", "2026-05-17"]


def test_grade_marks_hit_and_realized_return(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.grade("2026-05-16", results={"周六001": "胜"})
    row = store.load()[0]
    assert row["hit"] is True
    assert abs(row["realized_return"] - 3.10) < 1e-9


def test_grade_miss_returns_zero(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.grade("2026-05-16", results={"周六001": "负"})
    row = store.load()[0]
    assert row["hit"] is False
    assert row["realized_return"] == 0.0


def test_grade_only_touches_matching_ungraded_rows(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.record("2026-05-17", [_sig("周日002")], sporttery_odds={"周日002": 2.00})
    store.grade("2026-05-16", results={"周六001": "胜"})
    rows = store.load()
    assert rows[0]["hit"] is True
    assert rows[1]["hit"] is None  # different date untouched

    # re-grading the same date with a different (wrong) result must not flip
    store.grade("2026-05-16", results={"周六001": "负"})
    assert store.load()[0]["hit"] is True


def test_grade_skips_rows_without_a_result(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.grade("2026-05-16", results={"周六999": "胜"})
    assert store.load()[0]["hit"] is None


def test_load_handles_missing_file(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "does-not-exist.json")
    assert store.load() == []


def test_load_handles_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "conflict-signals.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = ConflictStore(path)
    assert store.load() == []
    # a record on top of corruption starts a fresh, valid list
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    assert len(store.load()) == 1
