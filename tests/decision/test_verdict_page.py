import json
from datetime import datetime
from zoneinfo import ZoneInfo

from nutmeg.decision.verdict_page import write_verdict

BJ = ZoneInfo("Asia/Shanghai")
DAY = "2026-09-27"


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_verdict_page_puts_overridden_signals_first_and_logs_the_edition(tmp_path):
    from nutmeg.decision.overrides import record_override

    day_dir = tmp_path / "jczq" / "daily" / DAY
    prior = {"home": 0.454, "draw": 0.23, "away": 0.316}
    _write(day_dir / "jczq-legs-base.json", {"legs": {"周日003": {
        "match_id": "m3", "name": "格拉夫-登博思", "kickoff_bj": f"{DAY}T20:30:00+08:00",
        "fair": prior}}})
    _write(day_dir / "reads.json", [{"match_id": "m3", "prior": prior, "belief": prior,
                                     "judgment_tier": "deep_research",
                                     "note": "[周日003|格拉夫-登博思|deep_research] x"}])
    _write(day_dir / "research-周日003.json", {
        "name": "格拉夫-登博思", "confidence": 2, "summary": "主队垫底",
        "stance": {"face": "3", "structure": "double", "cover": "0",
                   "tilt": {"shift": {"3": -5, "1": 0, "0": 5}, "expires_if": "x", "evidence": [
                       {"tier": "state", "kind": "form_state", "pp": 2, "source": "s",
                        "captured_at": f"{DAY}T08:00:00+08:00"}]}},
        "strength_balance": {"verdict": "even", "underdog_path": {"strength": "real"}}})
    record_override(day_dir / "research-周日003.json", tilt=None, note="公开信息已定价",
                    at=f"{DAY}T07:40:00+08:00", judge="claude", prior=prior)

    path = write_verdict(day=DAY, data_dir=tmp_path,
                         now=datetime(2026, 9, 27, 12, 30, tzinfo=BJ))

    html = path.read_text(encoding="utf-8")
    assert "需要你裁决" in html and "公开信息已定价" in html
    assert html.index("需要你裁决") < html.index("竞彩逐场")
    assert "主版" in html and "研究原判" in html
    assert "账房：" in html and "足彩初稿" not in html             # 无在售期 → 不画足彩块
    [log] = (day_dir / "verdict-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log)["overrides"] == 1


def test_edition_follows_the_clock(tmp_path):
    (tmp_path / "jczq" / "daily" / DAY).mkdir(parents=True)
    path = write_verdict(day=DAY, data_dir=tmp_path, now=datetime(2026, 9, 27, 18, 45, tzinfo=BJ))
    assert "晚版" in path.read_text(encoding="utf-8")


def test_verdict_page_shows_the_zucai_draft_for_the_issue_on_sale(tmp_path):
    from tests.decision.test_day_brief import _board

    (tmp_path / "jczq" / "daily" / DAY).mkdir(parents=True)
    _write(tmp_path / "zucai" / "26132-issue.json",
           {"issue_id": "26132", "sale_deadline": f"{DAY}T21:00:00+08:00"})
    _board(tmp_path)
    path = write_verdict(day=DAY, data_dir=tmp_path,
                         now=datetime(2026, 9, 27, 12, 30, tzinfo=BJ))
    html = path.read_text(encoding="utf-8")
    assert "足彩初稿 · 26132" in html and "初稿" in html and "刹车档" in html
    assert "已登记的票与审票" in html and "J1" in html and "⛔否决" in html
    assert "账房：本月净" in html
