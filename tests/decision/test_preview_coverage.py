"""买前预审覆盖率（版图第 2 版拓展 2）：实购票里，开球前留过同一张预审痕的占比。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nutmeg.decision.preview_coverage import line, load_previews, month, summarize


def _leg(key: str) -> SimpleNamespace:
    return SimpleNamespace(key=key)


def _slip(slip_id: str, *, channel: str = "jczq", placed_at: str = "2026-11-08",
          keys: tuple[str, ...] = ("周日006", "周日007"), issue: str = "",
          faces: dict | None = None, first_kickoff: str = "2026-11-08T19:30:00+08:00"):
    return SimpleNamespace(slip_id=slip_id, channel=channel, placed_at=placed_at, issue=issue,
                           legs=[_leg(k) for k in keys], faces=faces or {},
                           first_kickoff=first_kickoff, purchased=True)


def _preview(day: str, at: str, *, channel: str = "jczq", keys=("周日006", "周日007"),
             issue: str = "", faces: dict | None = None) -> dict:
    row = {"day": day, "at": at, "channel": channel, "issue": issue, "keys": list(keys)}
    if faces:
        row["faces"] = faces
    return row


def test_jczq_ticket_is_covered_by_a_same_day_same_matches_preview_before_kickoff():
    slips = [_slip("20261108-J1")]
    previews = [_preview("2026-11-08", "2026-11-08T13:00:00+08:00")]
    assert summarize(slips, previews) == {"n": 1, "covered": 1, "missing": []}


def test_a_preview_after_kickoff_or_for_other_matches_does_not_count():
    slips = [_slip("20261108-J1"), _slip("20261108-J2", keys=("周日012",))]
    previews = [
        _preview("2026-11-08", "2026-11-08T20:05:00+08:00"),                 # 开球之后
        _preview("2026-11-08", "2026-11-08T13:00:00+08:00", keys=("周日015",)),  # 别的场
        _preview("2026-11-01", "2026-11-01T13:00:00+08:00", keys=("周日012",)),  # 上周同编号
    ]
    out = summarize(slips, previews)
    assert out == {"n": 2, "covered": 0, "missing": ["20261108-J1", "20261108-J2"]}


def test_zucai_ticket_needs_the_same_issue_and_the_same_faces():
    faces = {"1": "31", "2": "0", "3": "310"}
    slips = [_slip("20261108-R1", channel="renjiu", issue="26162", keys=(), faces=faces,
                   first_kickoff="2026-11-08T22:00:00+08:00")]
    same = _preview("2026-11-07", "2026-11-07T18:00:00+08:00", channel="renjiu", issue="26162",
                    keys=("1", "2", "3"), faces={"1": "13", "2": "0", "3": "031"})
    other = _preview("2026-11-07", "2026-11-07T18:00:00+08:00", channel="renjiu", issue="26162",
                     keys=("1", "2", "3"), faces={"1": "3", "2": "0", "3": "310"})
    assert summarize(slips, [other])["covered"] == 0
    assert summarize(slips, [other, same])["covered"] == 1


def test_missing_kickoff_falls_back_to_the_matching_preview_without_a_time_check():
    slips = [_slip("20261008-J1", placed_at="2026-10-08", first_kickoff="")]
    previews = [_preview("2026-10-08", "2026-10-08T23:00:00+08:00")]
    assert summarize(slips, previews)["covered"] == 1


def test_load_previews_tags_each_row_with_its_day_folder_and_skips_bad_lines(tmp_path: Path):
    day = tmp_path / "daily" / "2026-11-08"
    day.mkdir(parents=True)
    (day / "previews.jsonl").write_text(
        json.dumps({"at": "2026-11-08T13:00:00+08:00", "channel": "jczq", "issue": "",
                    "keys": ["周日006"]}, ensure_ascii=False) + "\n{坏行\n", encoding="utf-8")
    rows = load_previews(tmp_path)
    assert [(r["day"], r["keys"]) for r in rows] == [("2026-11-08", ["周日006"])]


def test_month_on_an_empty_data_dir_reports_zero_tickets(tmp_path: Path):
    assert month(tmp_path, "2026-11") == {"n": 0, "covered": 0, "missing": []}


def test_line_names_the_unreviewed_tickets_and_says_so_when_it_cannot_compute():
    assert line({"n": 0, "covered": 0, "missing": []}) == "**买前预审**：本月没有实购票"
    text = line({"n": 4, "covered": 3, "missing": ["20261108-J3"]})
    assert "3/4" in text and "20261108-J3" in text
    assert "算不出" in line({"_error": "boom"})
    assert "算不出" in line(None)
