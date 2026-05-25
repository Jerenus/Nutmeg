"""Tests for jczq_tiered_review — spec §6."""
from __future__ import annotations

import json

from nutmeg.services.jczq_tiered_review import (
    _merge_cross_version_by_theme,
    load_cross_version_history_dict,
    load_cross_version_retired_themes,
)


def test_merge_cross_version_by_theme_sums_counts() -> None:
    v1 = {"平局收割": {"tickets": 23, "ticket_hits": 0,
                       "legs": 63, "leg_hits": 11}}
    v2 = {"平局收割": {"tickets": 5, "ticket_hits": 0,
                       "legs": 15, "leg_hits": 3}}
    merged = _merge_cross_version_by_theme(v1, v2)
    assert merged["平局收割"]["tickets"] == 28
    assert merged["平局收割"]["legs"] == 78


def test_load_cross_version_retired_reads_v1_only(tmp_path) -> None:
    v1_hist = [{"date": "2026-05-25", "chaos": 8,
                "anchor": None, "bold": {},
                "by_theme": {"平局收割":
                             {"tickets": 23, "ticket_hits": 0,
                              "legs": 63, "leg_hits": 11}}}]
    (tmp_path / "bold-review-history.json").write_text(
        json.dumps(v1_hist), encoding="utf-8"
    )
    retired = load_cross_version_retired_themes(tmp_path)
    assert any(rt.theme == "平局收割" for rt in retired)


def test_load_cross_version_history_dict_merges_both(tmp_path) -> None:
    v1_hist = [{"date": "2026-05-25", "chaos": 8,
                "anchor": None, "bold": {},
                "by_theme": {"平局收割":
                             {"tickets": 23, "ticket_hits": 0,
                              "legs": 63, "leg_hits": 11}}}]
    v2_hist = [{"date": "2026-05-26", "chaos": 5,
                "by_theme": {"平局收割":
                             {"tickets": 1, "ticket_hits": 0,
                              "legs": 3, "leg_hits": 1}}}]
    (tmp_path / "bold-review-history.json").write_text(
        json.dumps(v1_hist), encoding="utf-8"
    )
    (tmp_path / "tiered-plan-history.json").write_text(
        json.dumps(v2_hist), encoding="utf-8"
    )
    hist = load_cross_version_history_dict(tmp_path)
    slot = hist["by_theme"]["平局收割"]
    assert slot["tickets"] == 24
    assert slot["legs"] == 66


def test_load_cross_version_missing_files_returns_empty(tmp_path) -> None:
    assert load_cross_version_retired_themes(tmp_path) == ()
    assert load_cross_version_history_dict(tmp_path) == {"by_theme": {}}
