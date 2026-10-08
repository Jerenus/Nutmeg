"""2026-10-08 B5 收拢的公共件：去水、Brier、北京时间、JSON 读取、解码、claude -p 调用。"""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from nutmeg.data.http import decode
from nutmeg.data.prices import devig
from nutmeg.decision import claude_models
from nutmeg.decision.bj_time import BJ, aware, bj_iso, parse_bj
from nutmeg.decision.faces import CODE_OF, FACE_OF, FACES
from nutmeg.decision.files import read_json
from nutmeg.decision.jczq_board import build_board_legs
from nutmeg.decision.scoring import brier


def test_devig_guards_zero_and_unparseable_prices():
    fair = devig({"home": 2.0, "draw": "3.5", "away": 4.0})
    assert abs(sum(fair.values()) - 1.0) < 1e-12 and fair["home"] > fair["draw"] > fair["away"]
    assert set(devig({"home": 2.0, "draw": 0, "away": "n/a"})) == {"home"}
    assert devig({}) == {} and devig({"home": 0, "draw": None}) == {}
    assert devig({"home": 2.0, "draw": 3.5, "away": 4.0}) == {
        k: (1.0 / v) / sum(1.0 / x for x in (2.0, 3.5, 4.0))
        for k, v in {"home": 2.0, "draw": 3.5, "away": 4.0}.items()}


def test_board_skips_a_match_whose_odds_cannot_be_devigged(tmp_path):
    day = tmp_path / "daily" / "2026-09-19"
    day.mkdir(parents=True)
    (day / "bold_odds.json").write_text(json.dumps({
        "周五001": {"match_winner": {"odds": {"home": 2.0, "draw": 0, "away": 4.0}}},
        "周五002": {"match_winner": {"odds": {"home": 1.5, "draw": 4.0, "away": 6.0}}}}),
        encoding="utf-8")
    matches = [{"match_id": f"m-{i}", "home_team": "A", "away_team": "B", "competition": "x",
                "scheduled_at": "2026-09-19T19:00:00+08:00", "board_code": f"周五00{i}"}
               for i in (1, 2)]
    doc = build_board_legs(day="2026-09-19", matches=matches, jczq_dir=tmp_path,
                           now=datetime(2026, 9, 19, 9, tzinfo=BJ))
    assert list(doc["legs"]) == ["周五002"]


def test_brier_accepts_face_names_and_sporttery_codes_in_a_fixed_order():
    p = {"away": 0.2, "home": 0.5, "draw": 0.3}
    assert brier(p, "home") == brier(p, "3") == (0.5 - 1) ** 2 + 0.3 ** 2 + 0.2 ** 2
    assert brier(p, "0") == brier({"home": 0.5, "draw": 0.3, "away": 0.2}, "away")
    assert brier({"home": 1.0}, "total_3") == 1.0 + 1.0


def test_beijing_time_parsing():
    assert aware("2026-09-19 00:30") == datetime(2026, 9, 19, 0, 30, tzinfo=BJ)
    assert bj_iso("2026-09-19 00:30") == "2026-09-19T00:30:00+08:00"
    assert bj_iso("2026-09-18T16:30:00+00:00") == "2026-09-19T00:30:00+08:00"
    assert parse_bj(None) is None and parse_bj("") is None and parse_bj("soon") is None
    assert parse_bj("2026-09-19T00:30:00+09:00").utcoffset() == timedelta(hours=9)
    assert BJ.utcoffset(None) == timezone(timedelta(hours=8)).utcoffset(None)
    with pytest.raises(ValueError):
        aware("soon")


def test_read_json_returns_default_when_missing_or_corrupt(tmp_path):
    assert read_json(tmp_path / "missing.json", {"d": 1}) == {"d": 1}
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    assert read_json(tmp_path / "bad.json") is None
    (tmp_path / "ok.json").write_text('{"a": [1]}', encoding="utf-8")
    assert read_json(tmp_path / "ok.json", {}) == {"a": [1]}


def test_decode_tries_encodings_strictly_then_falls_back():
    gb = "周五001".encode("gb18030")
    assert decode("周五".encode(), ("utf-8-sig", "gb18030")) == "周五"
    assert decode(gb, ("utf-8-sig", "gb18030")) == "周五001"
    with pytest.raises(UnicodeDecodeError):
        decode(b"\xff\xfe\xfd", ("utf-8",))
    assert decode(b"ok\xff", ("utf-8",), errors="ignore") == "ok"


def test_face_maps_are_inverse():
    assert FACES == ("home", "draw", "away")
    assert {v: k for k, v in CODE_OF.items()} == FACE_OF


def test_run_claude_builds_one_argv_for_every_caller(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, timeout=kwargs["timeout"], input=kwargs["input"])
        return subprocess.CompletedProcess(argv, 0, stdout="out", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(claude_models, "claude_bin", lambda: "claude")
    code, out = claude_models.run_claude("sys", "in", model="sonnet",
                                         allowed_tools="WebSearch", max_turns="24", timeout=900)
    assert (code, out) == (0, "out") and seen["timeout"] == 900 and seen["input"] == "in"
    assert seen["argv"] == ["claude", "-p", "--model", "sonnet", "--system-prompt", "sys",
                            "--allowedTools", "WebSearch", "--max-turns", "24",
                            "--output-format", "text"]
