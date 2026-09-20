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
