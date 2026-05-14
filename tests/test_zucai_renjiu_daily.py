from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.services.zucai_renjiu_daily import (
    ZucaiRenjiuDailyService,
    ZucaiRenjiuValidationError,
)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, Path, str]] = []

    def send_document(self, *, chat_id: int, document_path: Path, caption: str):
        self.sent.append((chat_id, Path(document_path), caption))
        return {"ok": True}


def _write_issue_and_odds(tmp_path: Path) -> tuple[Path, Path]:
    matches = [
        (1, "英超", "伯恩利", "阿斯顿维拉", (5.10, 3.95, 1.47)),
        (2, "英超", "水晶宫", "埃弗顿", (2.73, 3.05, 2.30)),
        (3, "英超", "诺丁汉森林", "纽卡斯尔联", (2.57, 3.32, 2.28)),
        (4, "英超", "西汉姆联", "阿森纳", (5.50, 4.20, 1.41)),
        (5, "德甲", "汉堡", "弗赖堡", (2.46, 3.45, 2.31)),
        (6, "德甲", "科隆", "海登海姆", (1.90, 3.75, 2.98)),
        (7, "德甲", "美因茨", "柏林联合", (1.58, 3.80, 4.28)),
        (8, "意甲", "克雷莫纳", "比萨", (1.56, 3.55, 4.85)),
        (9, "意甲", "佛罗伦萨", "热那亚", (1.89, 3.15, 3.55)),
        (10, "意甲", "帕尔马", "罗马", (6.42, 4.10, 1.37)),
        (11, "意甲", "AC米兰", "亚特兰大", (1.90, 3.28, 3.35)),
        (12, "西甲", "毕尔巴鄂竞技", "巴伦西亚", (1.60, 3.50, 4.58)),
        (13, "西甲", "皇家奥维耶多", "赫塔费", (2.79, 2.70, 2.50)),
        (14, "西甲", "巴塞罗那", "皇家马德里", (1.51, 4.65, 3.96)),
    ]
    issue = {
        "issue_id": "26074",
        "game_type": "sfc14",
        "sale_start": "2026-05-06 20:00",
        "sale_stop": "2026-05-10 20:30",
        "draw_date": "2026-05-11",
        "sources": [{"label": "official schedule", "url": "https://example.test/schedule"}],
        "matches": [
            {
                "match_no": no,
                "competition": league,
                "home_team": home,
                "away_team": away,
                "match_date": "2026-05-10",
            }
            for no, league, home, away, _odds in matches
        ],
    }
    odds = {
        "issue_id": "26074",
        "captured_at": "2026-05-10 12:58:47",
        "sources": [{"label": "odds", "url": "https://example.test/odds"}],
        "matches": [
            {
                "match_no": no,
                "home": values[0],
                "draw": values[1],
                "away": values[2],
            }
            for no, _league, _home, _away, values in matches
        ],
    }
    issue_path = tmp_path / "26074-issue.json"
    odds_path = tmp_path / "26074-odds.json"
    issue_path.write_text(json.dumps(issue, ensure_ascii=False), encoding="utf-8")
    odds_path.write_text(json.dumps(odds, ensure_ascii=False), encoding="utf-8")
    return issue_path, odds_path


def test_renjiu_daily_generates_three_budget_tiers(tmp_path: Path) -> None:
    issue_path, odds_path = _write_issue_and_odds(tmp_path)

    report = ZucaiRenjiuDailyService().build_report(
        run_date="2026-05-10",
        issue_file=issue_path,
        odds_file=odds_path,
        output_dir=tmp_path / "out",
    )

    assert [ticket.ticket_id for ticket in report.tickets] == [
        "conservative",
        "main",
        "aggressive",
    ]
    costs = {ticket.ticket_id: ticket.cost_yuan for ticket in report.tickets}
    assert 64 <= costs["conservative"] <= 100
    assert 100 <= costs["main"] <= 200
    assert 200 <= costs["aggressive"] <= 400
    assert report.recommended_ticket_id == "main"
    assert len(report.least_confident_matches) == 5
    assert all(len(ticket.picks) == 14 for ticket in report.tickets)


def test_renjiu_daily_writes_artifacts_and_pdf(tmp_path: Path) -> None:
    issue_path, odds_path = _write_issue_and_odds(tmp_path)

    report = ZucaiRenjiuDailyService().build_report(
        run_date="2026-05-10",
        issue_file=issue_path,
        odds_file=odds_path,
        output_dir=tmp_path / "out",
        render_pdf=True,
    )

    assert report.artifacts.markdown_path is not None
    assert report.artifacts.json_path is not None
    assert report.artifacts.pdf_path is not None
    markdown = Path(report.artifacts.markdown_path).read_text(encoding="utf-8")
    assert "保守票" in markdown
    assert "主推票" in markdown
    assert "进攻票" in markdown
    assert Path(report.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    payload = json.loads(Path(report.artifacts.json_path).read_text(encoding="utf-8"))
    assert payload["recommended_ticket_id"] == "main"


def test_renjiu_daily_dry_run_dispatch_keeps_pdf_available(tmp_path: Path) -> None:
    issue_path, odds_path = _write_issue_and_odds(tmp_path)
    sender = RecordingSender()

    report = ZucaiRenjiuDailyService(
        telegram_sender=sender,
        telegram_chat_ids=[123],
    ).build_report(
        run_date="2026-05-10",
        issue_file=issue_path,
        odds_file=odds_path,
        output_dir=tmp_path / "out",
        dispatch_telegram=True,
        dry_run=True,
    )

    assert report.dispatch.status == "dry_run"
    assert report.artifacts.pdf_path is not None
    assert sender.sent == []


def test_renjiu_daily_rejects_incomplete_issue(tmp_path: Path) -> None:
    issue_path, odds_path = _write_issue_and_odds(tmp_path)
    payload = json.loads(issue_path.read_text(encoding="utf-8"))
    payload["matches"] = payload["matches"][:13]
    issue_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ZucaiRenjiuValidationError, match="exactly 14"):
        ZucaiRenjiuDailyService().build_report(
            run_date="2026-05-10",
            issue_file=issue_path,
            odds_file=odds_path,
            output_dir=tmp_path / "out",
        )
