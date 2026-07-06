"""jczq-report CLI(世界杯 PDF 日报,launchd wc-report-20 驱动)。"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _seed_minimal_day(root: Path, day: str = "2026-06-12") -> None:
    daily = root / "daily" / day
    daily.mkdir(parents=True)
    (daily / "today-packet.md").write_text(
        "# packet\n## A. 引擎票面(确定性,勿改腿)\n(空)\n", encoding="utf-8"
    )
    wc = root / "wc2026"
    wc.mkdir(parents=True)
    sim = {"run_date": day, "seed": 1, "n_sims": 10, "anchored": [],
           "probs": {"Mexico": {k: 0.3 for k in
                                ("qualify", "r32", "r16", "qf", "sf",
                                 "final", "champion")}}}
    (wc / f"sim-{day}.json").write_text(json.dumps(sim), encoding="utf-8")


def test_jczq_report_writes_pdf(tmp_path: Path) -> None:
    _seed_minimal_day(tmp_path)
    result = runner.invoke(app, [
        "jczq-report", "--date", "2026-06-12", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    pdf = tmp_path / "daily" / "2026-06-12" / "wc-daily-report.pdf"
    assert pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-"


def test_jczq_report_if_missing_skips_second_run(tmp_path: Path) -> None:
    _seed_minimal_day(tmp_path)
    args = ["jczq-report", "--date", "2026-06-12", "--output-dir", str(tmp_path),
            "--if-missing"]
    assert runner.invoke(app, args).exit_code == 0
    pdf = tmp_path / "daily" / "2026-06-12" / "wc-daily-report.pdf"
    mtime = pdf.stat().st_mtime_ns
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert pdf.stat().st_mtime_ns == mtime  # 没重写
    assert "已存在" in result.output


def test_jczq_report_review_pdf_variant(tmp_path: Path) -> None:
    _seed_minimal_day(tmp_path)
    result = runner.invoke(app, [
        "jczq-report", "--date", "2026-06-12", "--output-dir", str(tmp_path),
        "--review-pdf"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "daily" / "2026-06-12" / "wc-review-report.pdf").exists()


def test_jczq_report_reconciles_recent_predictions(tmp_path: Path) -> None:
    """跑 jczq-report 前自动对账最近判定 → ledger 落盘。"""
    import json

    # 判定日须在评判员层上线日(LEDGER_START_DATE=2026-06-12)之后才入账
    _seed_minimal_day(tmp_path, day="2026-06-13")
    prev = tmp_path / "daily" / "2026-06-12"
    prev.mkdir(parents=True)
    (prev / "predictions.json").write_text(json.dumps({
        "date": "2026-06-12", "judge": "claude",
        "picks": [{"fixture": "A vs B", "match_id": "M01", "judgment": "home",
                   "score": "2-1", "reason": "r", "confidence": 4}],
        "champion_pick": {"team": "Argentina", "reason": "x"},
        "opinion_ticket": None, "written_at": "t",
    }, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "wc2026" / "results.json").write_text(json.dumps([
        {"match_id": "M01", "home": "A", "away": "B", "status": "FT",
         "outcome_90": "home", "goals_h_90": 2, "goals_a_90": 1,
         "advanced": None}]), encoding="utf-8")
    result = runner.invoke(app, [
        "jczq-report", "--date", "2026-06-13", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    ledger = (tmp_path / "wc2026" / "judge-ledger.jsonl").read_text(
        encoding="utf-8")
    assert '"judgment_hit": true' in ledger
