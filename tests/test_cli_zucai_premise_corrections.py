"""`zucai-premise-corrections` 要跳过拒收件（`<期>-research-m12.rejected.json`）。

2026-10-12 出生事故：26139 场 12 两次拒收后留下 `26139-research-m12.rejected.json`，
glob `*-research-m*.json` 把它也捞进来，`int("12.rejected")` 直接炸，整条命令不可用。
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_rejected_research_files_are_skipped(tmp_path: Path):
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26139-research-m9.json").write_text(json.dumps({
        "name": "m9",
        "premise_corrections": [{
            "subject": "swe-elfsborg", "subject_type": "team", "field": "coach_2026_02_19",
            "given": "", "correct": "Björn Hamberg", "evidence": "elfsborg.se 2026-02-19",
            "as_of": "2026-10-12",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (zdir / "26139-research-m12.rejected.json").write_text(json.dumps({
        "code": "足彩26139-12", "attempts": 2, "error": "stance: market_read 不合法",
    }), encoding="utf-8")

    out = runner.invoke(app, ["zucai-premise-corrections", "--issue", "26139",
                              "--research-dir", str(zdir)])

    assert out.exit_code == 0, out.output
    assert "前提纠正 1 条" in out.output and "场9" in out.output
