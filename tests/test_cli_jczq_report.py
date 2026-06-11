"""jczq-today --refresh-check 与 jczq-report CLI。"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli.jczq import _board_changed

runner = CliRunner()


def test_board_changed_detects_new_match() -> None:
    # 真实快照结构：matchInfoList（按日分组）→ subMatchList → matchNumStr
    # （对齐 bold_matches_from_sporttery 的解析口径）。
    old = {"matchInfoList": [{"subMatchList": [{"matchNumStr": "周四001"}]}]}
    new = {
        "matchInfoList": [
            {
                "subMatchList": [
                    {"matchNumStr": "周四001"},
                    {"matchNumStr": "周四002"},
                ]
            }
        ]
    }
    assert _board_changed(old, new) is True
    assert _board_changed(old, old) is False


def test_board_changed_none_snapshot_means_changed() -> None:
    assert _board_changed(None, {"matchInfoList": []}) is True


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
