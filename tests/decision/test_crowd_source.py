import json

import pytest

from nutmeg.decision.crowd_source import (
    CrowdMatch,
    backfill,
    fetch_issue,
    load_board,
    parse_zgzcw,
)
from tests.decision.crowd_fixtures import zg_doc


def test_parse_devigs_and_numbers_matches_in_order():
    board = parse_zgzcw(zg_doc())
    assert len(board) == 14 and [m.no for m in board] == list(range(1, 15))
    m = board[0]
    assert abs(sum(m.p.values()) - 1) < 1e-9 and m.p["3"] > m.p["1"] > m.p["0"]
    assert m.fav_face == "3" and m.league_group == "top5"


def test_parse_skips_bad_rows_but_keeps_numbering():
    doc = zg_doc()
    doc["matchInfo"][1]["europeSp"] = ""
    board = parse_zgzcw(doc)
    assert [m.no for m in board][:2] == [1, 3]


def test_league_groups():
    assert CrowdMatch(1, "欧国联", "a", "b", {"3": .5, "1": .3, "0": .2}).league_group == "national"
    assert CrowdMatch(1, "德乙", "a", "b", {"3": .5, "1": .3, "0": .2}).league_group == "other"


def test_fetch_appends_snapshots_and_load_returns_last(tmp_path):
    times = iter(["2026-10-08T09:00:00+08:00", "2026-10-08T14:00:00+08:00"])
    from datetime import datetime
    for _ in range(2):
        fetch_issue(tmp_path, "26136", fetcher=lambda url: zg_doc(),
                    now=datetime.fromisoformat(next(times)))
    doc = json.loads((tmp_path / "26136-zgzcw.json").read_text("utf-8"))
    assert len(doc["snapshots"]) == 2 and "issue=26136" in doc["source"]
    at, board = load_board(tmp_path, "26136")
    assert at.startswith("2026-10-08T14:00") and len(board) == 14


def test_fetch_refuses_empty_board(tmp_path):
    with pytest.raises(ValueError):
        fetch_issue(tmp_path, "26136", fetcher=lambda url: {"matchInfo": []})
    assert not (tmp_path / "26136-zgzcw.json").exists()


def test_backfill_skips_existing_and_reports_failures(tmp_path):
    fetch_issue(tmp_path, "26035", fetcher=lambda url: zg_doc())

    def fetcher(url):
        if "26037" in url:
            raise OSError("timeout")
        return zg_doc()

    out = backfill(tmp_path, ["26035", "26036", "26037"], fetcher=fetcher, sleep=lambda s: None)
    assert out["26035"] == "skip" and out["26036"] == "ok" and out["26037"].startswith("fail")
