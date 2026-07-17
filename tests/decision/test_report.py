"""decision-report:清洁版 PDF 日报(当日每场 Read/偏移/CLV + Ticket + 双轴校准)
+ Telegram 推送。PDF 生成不打网、不真推 Telegram。

内容逻辑与 PDF 二进制分离:``_report_blocks`` 是单一内容真源(可作字符串断言),
``render_report_pdf`` 只把 blocks 薄渲染成 PDF —— 故"含当日场次文本"断言打在 blocks 上,
PDF 只验非空 + %PDF 头(避免解析压缩内容流的脆性)。
"""
from typer.testing import CliRunner

from nutmeg.decision.ontology import Match, Read, Settlement, Ticket
from nutmeg.decision.report import (
    _report_blocks,
    render_report_pdf,
    run_report,
)
from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.cli import app

runner = CliRunner()
_DATE = "2026-07-08"
_M1 = f"M-{_DATE}-阿尔法-贝塔"
_M2 = f"M-{_DATE}-伽马-德尔塔"
_OTHER = "M-2026-07-09-泽塔-伊塔"       # 次日场,应被当日过滤掉


def _seed(tmp_path) -> DecisionStore:
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Match(match_id=_M1, kickoff_at=f"{_DATE}T22:00:00+08:00",
                       home="阿尔法", away="贝塔", competition="世界杯"))
    store.upsert(Match(match_id=_M2, kickoff_at=f"{_DATE}T22:00:00+08:00",
                       home="伽马", away="德尔塔", competition="世界杯"))
    store.upsert(Match(match_id=_OTHER, kickoff_at="2026-07-09T22:00:00+08:00",
                       home="泽塔", away="伊塔", competition="世界杯"))
    # 判读(偏移市场):belief 偏离 prior
    store.upsert(Read(read_id="R-1", match_id=_M1, snapshot_id="S-1", made_at=f"{_DATE}T15:00",
                      judge="claude", market="had",
                      prior={"home": 0.42, "draw": 0.28, "away": 0.30},
                      belief={"home": 0.30, "draw": 0.40, "away": 0.30},
                      confidence=4, note="站平", shadow=False))
    # 市场基线 shadow(跟市场)
    store.upsert(Read(read_id="R-2", match_id=_M2, snapshot_id="S-2", made_at=f"{_DATE}T15:00",
                      judge="shadow", market="had",
                      prior={"home": 0.50, "draw": 0.25, "away": 0.25},
                      belief={"home": 0.50, "draw": 0.25, "away": 0.25}, shadow=True))
    # 次日场的判读(不应出现在当日报告)
    store.upsert(Read(read_id="R-9", match_id=_OTHER, snapshot_id="S-9", made_at="2026-07-09T15:00",
                      judge="claude", market="had",
                      prior={"home": 0.4, "draw": 0.3, "away": 0.3},
                      belief={"home": 0.4, "draw": 0.3, "away": 0.3}, shadow=False))
    # 结算(带 Brier + CLV)
    store.upsert(Settlement(settlement_id="SET-read-R-1", ref_type="read", ref_id="R-1",
                            settled_at=f"{_DATE}T23:59", outcome_90="draw",
                            brier=0.34, clv_pp=0.021, hit=True))
    # 今日票(经 legs.match_id 归属当日)
    store.upsert(Ticket(ticket_id="T-1", channel="jczq", made_at=f"{_DATE}T15:30",
                        legs=[{"match_id": _M1, "market": "had", "selection": "draw",
                               "odds": 3.35, "bucket": "draw"}],
                        structure="single", stake_yuan=40, tag="draw",
                        budget_bucket="draw_single"))
    return store


def test_render_report_pdf_returns_nonempty_pdf_bytes(tmp_path):
    pdf = render_report_pdf(_seed(tmp_path), _DATE)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF" and len(pdf) > 800


def test_report_blocks_contain_todays_matches_only(tmp_path):
    blocks = _report_blocks(_seed(tmp_path), _DATE)
    text = "\n".join(t for _kind, t in blocks)
    assert _DATE in text                       # 报头含当日日期
    assert "阿尔法 vs 贝塔" in text            # 当日场次
    assert "伽马 vs 德尔塔" in text
    assert "泽塔" not in text                  # 次日场被过滤
    # 偏移(判读 vs 市场)+ CLV/Brier 出现在报告
    assert "偏移" in text
    assert "CLV" in text and "Brier" in text
    # 今日票出现
    assert "T-1" in text or "40" in text


def test_report_blocks_empty_store_still_valid(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    blocks = _report_blocks(store, _DATE)
    text = "\n".join(t for _k, t in blocks)
    assert _DATE in text                       # 空库仍出报告(缺节标注)
    pdf = render_report_pdf(store, _DATE)
    assert pdf[:4] == b"%PDF"


def test_decision_report_cli_dry_run(tmp_path):
    _seed(tmp_path)
    result = runner.invoke(app, ["decision-report", "--date", _DATE,
                                 "--output-dir", str(tmp_path),
                                 "--dispatch-telegram"])   # dry_run 默认 True
    assert result.exit_code == 0, result.output
    pdf_path = tmp_path / "daily" / _DATE / f"decision-report-{_DATE}.pdf"
    assert pdf_path.exists() and pdf_path.read_bytes()[:4] == b"%PDF"
    assert "dry_run" in result.output or "dry-run" in result.output


class _RecordingNotificationService:
    def __init__(self):
        self.calls = []

    def publish(self, request, *, dry_run=False):
        from nutmeg.notifications.models import NotificationOutcome

        self.calls.append((request, dry_run))
        return NotificationOutcome.sent_for_test("N-1", "91")


def test_run_report_publishes_stage_aware_semantic_notification(tmp_path):
    _seed(tmp_path)
    notifier = _RecordingNotificationService()

    first = run_report(
        _DATE,
        tmp_path,
        dispatch_telegram=True,
        dry_run=False,
        stage="close",
        notification_service=notifier,
    )
    second = run_report(
        _DATE,
        tmp_path,
        dispatch_telegram=True,
        dry_run=False,
        stage="settle",
        notification_service=notifier,
    )

    assert first.notification.status.value == "sent"
    assert second.notification.status.value == "sent"
    assert [call[0].stage for call in notifier.calls] == ["close", "settle"]
    assert notifier.calls[0][0].semantic_fingerprint != notifier.calls[1][0].semantic_fingerprint
    assert first.pdf_path == second.pdf_path
