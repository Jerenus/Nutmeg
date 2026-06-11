"""PDF 日报 smoke test — 非空、可生成、缺数据可降级(spec §7)。"""
from __future__ import annotations

from pathlib import Path

from nutmeg.services.worldcup.report_data import DailyReport
from nutmeg.services.worldcup.report_pdf import render_daily_pdf, render_review_pdf
from nutmeg.services.worldcup.sim import SimOutput

KEYS = ("qualify", "r32", "r16", "qf", "sf", "final", "champion")


def _report(with_sim: bool) -> DailyReport:
    sim = SimOutput(
        run_date="2026-06-12", seed=1, n_sims=100,
        probs={"Mexico": dict.fromkeys(KEYS, 0.3)},
    ) if with_sim else None
    return DailyReport(
        run_date="2026-06-12", stage_label="小组赛",
        narrative="今天 3 场在售。", packet_md="## A. 引擎票面\n(空)",
        answers=None, sim=sim, sim_prev=None, sim_history=[sim] if sim else [],
        review=None, calibration_note=None,
    )


def test_render_daily_pdf(tmp_path: Path) -> None:
    out = tmp_path / "wc-daily-report.pdf"
    render_daily_pdf(_report(with_sim=True), out)
    assert out.exists() and out.stat().st_size > 5000
    assert out.read_bytes()[:5] == b"%PDF-"


def test_render_daily_pdf_without_sim_still_renders(tmp_path: Path) -> None:
    out = tmp_path / "x.pdf"
    render_daily_pdf(_report(with_sim=False), out)
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"


def test_render_review_pdf(tmp_path: Path) -> None:
    out = tmp_path / "wc-review-report.pdf"
    r = _report(with_sim=True)
    r.review = {"by_version": {}, "total_stake": 100, "total_return": 0}
    render_review_pdf(r, out)
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
