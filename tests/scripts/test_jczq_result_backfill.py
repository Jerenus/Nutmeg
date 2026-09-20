from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "jczq_result_backfill.py"
_SPEC = importlib.util.spec_from_file_location("jczq_result_backfill", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
backfill = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backfill)


class _FailingClient:
    def __init__(self, **_kwargs):
        pass

    def get(self, _url):
        raise RuntimeError("offline")

    def close(self):
        pass


class _Response:
    def __init__(self, text: str):
        self.content = text.encode()

    def raise_for_status(self):
        pass


class _StaticClient:
    payload = ""

    def __init__(self, **_kwargs):
        pass

    def get(self, _url):
        return _Response(self.payload)

    def close(self):
        pass


def _board(codes: list[str]) -> dict:
    return {
        "matchInfoList": [
            {
                "businessDate": "2026-09-20",
                "subMatchList": [
                    {"businessDate": "2026-09-20", "matchNumStr": code}
                    for code in codes
                ],
            }
        ]
    }


def _result_payload(codes: list[str]) -> str:
    rows = []
    for index, code in enumerate(codes, start=1):
        fields = [""] * 23
        fields[0] = str(index)
        fields[4] = code
        fields[11:15] = ["2", "1", "1", "0"]
        fields[22] = "0"
        rows.append("^".join(fields))
    return "$" + "!".join(rows)


def test_stale_warning_is_first_line_and_exit_code_is_two(tmp_path, monkeypatch, capsys):
    daily = tmp_path / "daily"
    (daily / "2026-09-18").mkdir(parents=True)
    (daily / "2026-09-18" / "sporttery_markets.json").write_text("{}")
    out = tmp_path / "jc-results.json"
    out.write_text(json.dumps({"2026-09-17": {}}), encoding="utf-8")
    monkeypatch.setattr(backfill, "DAILY", daily)
    monkeypatch.setattr(backfill, "OUT", out)
    monkeypatch.setattr(backfill.httpx, "Client", _FailingClient)

    exit_code = backfill.collect(0, today=date(2026, 9, 20))

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "⚠️RESULTS_STALE: latest=2026-09-17 lag=3d"
    assert any("RuntimeError offline" in line for line in lines[1:])
    assert exit_code == 2


def test_two_day_lag_is_not_stale(tmp_path, monkeypatch, capsys):
    daily = tmp_path / "daily"
    daily.mkdir()
    out = tmp_path / "jc-results.json"
    out.write_text(json.dumps({"2026-09-18": {}}), encoding="utf-8")
    monkeypatch.setattr(backfill, "DAILY", daily)
    monkeypatch.setattr(backfill, "OUT", out)

    assert backfill.collect(0, today=date(2026, 9, 20)) == 0
    assert "RESULTS_STALE" not in capsys.readouterr().out


def test_current_day_is_not_sealed_until_all_board_results_exist(
    tmp_path, monkeypatch, capsys
):
    codes = [f"周日{i:03d}" for i in range(1, 31)]
    daily = tmp_path / "daily"
    day_dir = daily / "2026-09-20"
    day_dir.mkdir(parents=True)
    (day_dir / "sporttery_markets.json").write_text(
        json.dumps(_board(codes)), encoding="utf-8"
    )
    out = tmp_path / "jc-results.json"
    out.write_text(
        json.dumps({"2026-09-20": {codes[0]: {"ft_home": 2, "ft_away": 1}}}),
        encoding="utf-8",
    )
    _StaticClient.payload = _result_payload(codes[:1])
    monkeypatch.setattr(backfill, "DAILY", daily)
    monkeypatch.setattr(backfill, "OUT", out)
    monkeypatch.setattr(backfill.httpx, "Client", _StaticClient)

    assert backfill.collect(0, today=date(2026, 9, 20)) == 2

    stored = json.loads(out.read_text(encoding="utf-8"))
    assert "2026-09-20" not in stored
    assert capsys.readouterr().out.splitlines()[0] == (
        "⚠️RESULTS_STALE: incomplete=2026-09-20(1/30)"
    )


def test_historical_day_is_sealed_when_all_board_results_exist(tmp_path, monkeypatch):
    codes = [f"周一{i:03d}" for i in range(1, 15)]
    daily = tmp_path / "daily"
    day_dir = daily / "2026-09-14"
    day_dir.mkdir(parents=True)
    board = _board(codes)
    board["matchInfoList"][0]["businessDate"] = "2026-09-14"
    for match in board["matchInfoList"][0]["subMatchList"]:
        match["businessDate"] = "2026-09-14"
    (day_dir / "sporttery_markets.json").write_text(
        json.dumps(board), encoding="utf-8"
    )
    out = tmp_path / "jc-results.json"
    out.write_text("{}", encoding="utf-8")
    _StaticClient.payload = _result_payload(codes)
    monkeypatch.setattr(backfill, "DAILY", daily)
    monkeypatch.setattr(backfill, "OUT", out)
    monkeypatch.setattr(backfill.httpx, "Client", _StaticClient)

    backfill.collect(0, today=date(2026, 9, 20))

    stored = json.loads(out.read_text(encoding="utf-8"))
    assert set(stored["2026-09-14"]) == set(codes)
