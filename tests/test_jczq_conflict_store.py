from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.data.european_odds import CrossCheckSignal
from nutmeg.services.jczq_conflict_store import (
    ConflictStore,
    StakePhase,
    resolve_stake_phase,
)


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


# --- stake ladder -----------------------------------------------------------


def test_stake_phase_observe_when_evidence_is_thin() -> None:
    phase = resolve_stake_phase(graded_count=5, rolling_roi=1.2)
    assert phase.name == "OBSERVE"
    assert phase.max_pct_per_signal == 0.02


def test_stake_phase_small_at_15_with_roi_above_one() -> None:
    phase = resolve_stake_phase(graded_count=20, rolling_roi=1.05)
    assert phase.name == "SMALL"
    assert phase.max_pct_per_signal == 0.10


def test_stake_phase_normal_at_40_with_strong_roi() -> None:
    phase = resolve_stake_phase(graded_count=50, rolling_roi=1.10)
    assert phase.name == "NORMAL"
    assert phase.max_pct_per_signal == 0.30


def test_stake_phase_kill_when_roi_collapses() -> None:
    phase = resolve_stake_phase(graded_count=30, rolling_roi=0.90)
    assert phase.name == "KILL"
    assert phase.max_pct_per_signal == 0.0


def test_stake_phase_kill_takes_precedence_over_normal() -> None:
    # plenty of evidence but ROI is bad → KILL wins, not NORMAL
    assert resolve_stake_phase(graded_count=50, rolling_roi=0.90).name == "KILL"


def test_stake_phase_boundary_normal_needs_roi_strictly_above_1_05() -> None:
    # graded_count high enough but ROI exactly 1.05 → not NORMAL, falls to SMALL
    assert resolve_stake_phase(graded_count=50, rolling_roi=1.05).name == "SMALL"


def test_stake_phase_boundary_small_needs_roi_strictly_above_1() -> None:
    # ROI exactly 1.0 → not SMALL, falls to OBSERVE
    assert resolve_stake_phase(graded_count=20, rolling_roi=1.0).name == "OBSERVE"


def test_stake_phase_kill_needs_25_graded() -> None:
    # bad ROI but only 20 graded → still OBSERVE, not KILL
    assert resolve_stake_phase(graded_count=20, rolling_roi=0.5).name == "OBSERVE"


def test_stake_phase_is_a_frozen_dataclass() -> None:
    import dataclasses

    phase = resolve_stake_phase(graded_count=0, rolling_roi=1.0)
    assert isinstance(phase, StakePhase)
    assert phase.note
    with pytest.raises(dataclasses.FrozenInstanceError):
        phase.name = "MUTATED"  # type: ignore[misc]


def test_store_phase_on_empty_store_is_observe(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    phase = store.phase()
    assert phase.name == "OBSERVE"


def test_store_phase_ignores_ungraded_rows(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    # one recorded but ungraded row → graded_count 0 → ROI defaults to 1.0
    assert store.phase().name == "OBSERVE"


def test_store_phase_computes_rolling_roi_over_graded_rows(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path / "conflict-signals.json")
    # 20 graded rows: 10 hits at odds 2.4 (return 2.4), 10 misses (return 0.0)
    # → rolling ROI = (10 * 2.4) / 20 = 1.2  → SMALL (count 20, roi > 1.0)
    for idx in range(10):
        store.record(
            "2026-05-16", [_sig(f"hit{idx}")], sporttery_odds={f"hit{idx}": 2.4}
        )
        store.record(
            "2026-05-16", [_sig(f"miss{idx}")], sporttery_odds={f"miss{idx}": 2.4}
        )
    results = {f"hit{idx}": "胜" for idx in range(10)}
    results.update({f"miss{idx}": "负" for idx in range(10)})
    store.grade("2026-05-16", results=results)
    phase = store.phase()
    assert phase.name == "SMALL"
