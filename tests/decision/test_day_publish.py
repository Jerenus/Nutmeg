import json
from pathlib import Path

import pytest

from nutmeg.decision.day_publish import PublishError, public_view, publish_day


def _data(tmp_path: Path) -> tuple[Path, Path]:
    data, root = tmp_path / "data", tmp_path / "root"
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({
        "date": "2026-09-23", "generated_at": "2026-09-23T12:00:00+08:00",
        "jczq": {"matches": [{
            "code": "周三001", "name": "A vs B", "competition": "英超",
            "kickoff_bj": "2026-09-23T19:30:00+08:00",
            "market": {"fair": {"home": .52, "draw": .26, "away": .22}, "drift_pp": 2.0},
            "labels": {"judgment_tier": "deep_research", "anchor_integrity": "pass"},
            "research": {"status": "done", "prospective": True,
                        "summary": "秘密内部备注 .nutmeg-data/x"},
            "read": {"judge": "ai:jczq-analyst", "status": "draft", "moved_pp": 6.0,
                    "confidence": 4},
            "ladder": "偏移",
            "logic": {"status": "ok", "text": "锚方完整度 pass 定了面。",
                     "cites": ["labels.anchor_integrity"]}}],
                 "counts": {"matches": 1, "deep_research": 1, "price_only": 0, "drafts": 1}},
        "zucai": {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00",
                  "prep": {}},
        "rsi": {"human_actions": ["因子 C11：propose_zero"], "failed_steps": []},
        "factors": [], "errors": []}), encoding="utf-8")
    (out / "decisions.json").write_text(json.dumps(
        [{"id": "read:周三001", "kind": "approve_read", "status": "open"}]), encoding="utf-8")
    (out / "discussion.jsonl").write_text('{"who":"jun","text":"私下讨论"}\n', encoding="utf-8")
    (root / "experiments").mkdir(parents=True)
    (root / "experiments" / "scoreboard-tallies.json").write_text(json.dumps({"chains": {
        "被排面链": {"n": 291, "issues": 18, "R_pp": -2.3, "ci_contains_zero": True,
                  "verdict": "falsified", "status": "falsified",
                  "raw": "⛔证伪", "machine_readable": True}},
        "coverage": {"chains": 1, "machine_readable": 1}}), encoding="utf-8")
    return data, root


def test_public_view_drops_internal_fields(tmp_path: Path):
    data, root = _data(tmp_path)
    view = public_view(data_dir=data, root=root, date="2026-09-23")
    m = view["matches"][0]
    assert set(m) == {"code", "name", "competition", "kickoff", "fair", "drift_pp", "tier",
                      "ladder", "judge", "confidence", "research_status", "prospective",
                      "logic"}
    assert m["logic"] == "锚方完整度 pass 定了面。"
    assert "summary" not in json.dumps(m) and view["decisions"] == {"open": 1, "total": 1}
    assert view["zucai"] == {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00",
                             "brief": None, "draft": [], "slips": [],
                             "plan_status": "未登记"}
    assert view["account"] is None and view["jczq_slips"] == []
    assert view["record"]["chains"][0]["name"] == "被排面链"
    assert view["record"]["coverage"]["chains"] == 1


def test_public_view_carries_draft_slips_and_account_without_notes(tmp_path: Path):
    data, root = _data(tmp_path)
    out = data / "daily" / "2026-09-23" / "brief.json"
    brief = json.loads(out.read_text("utf-8"))
    brief["account"] = {"line": "本月净 -120（1 条入账）／止损线 −3,000", "net": -120}
    brief["zucai"]["draft"] = [{"label": "初稿", "channel": "renjiu", "stake_yuan": 256,
                                "notes": 128, "p_all": 0.074, "ratio": 1.03, "vetoed": False,
                                "faces": "2:10 3:10", "lines": ["ℹ️V1 期望回报率 1.03"]}]
    brief["zucai"]["slips"] = [{"slip_id": "J1", "channel": "renjiu", "stake_yuan": 64,
                                "p_all": 0.05, "ratio": 0.9, "vetoed": True, "purchased": True,
                                "text": "2:10 3:3", "note": "私下备注 .nutmeg-data/x",
                                "lines": ["⛔V2 与已购票共享裸单"]}]
    out.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    view = public_view(data_dir=data, root=root, date="2026-09-23")
    assert view["account"].startswith("本月净 -120")
    assert view["zucai"]["plan_status"] == "已登记实票"
    assert view["zucai"]["draft"][0]["faces"] == "2:10 3:10"
    assert "note" not in view["zucai"]["slips"][0] and "lines" not in view["zucai"]["slips"][0]
    publish_day(data_dir=data, root=root, date="2026-09-23", out_dir=tmp_path / "site")
    day = (tmp_path / "site" / "2026-09-23" / "index.html").read_text(encoding="utf-8")
    assert "初稿·任九" in day and "⛔否决" in day and "账房：本月净 -120" in day
    assert "私下备注" not in day


def test_publish_day_writes_four_pages_and_scrubs(tmp_path: Path):
    data, root = _data(tmp_path)
    report = publish_day(data_dir=data, root=root, date="2026-09-23", out_dir=tmp_path / "site")
    for rel in ("2026-09-23/index.html", "index.html", "method.html", "record.html"):
        html = (tmp_path / "site" / rel).read_text(encoding="utf-8")
        assert ".nutmeg-data" not in html and "私下讨论" not in html
        assert "discussion" not in html, rel
    day = (tmp_path / "site" / "2026-09-23" / "index.html").read_text(encoding="utf-8")
    assert "A vs B" in day and "锚方完整度 pass 定了面。" in day and "空仓" in day
    assert "被排面链" in (tmp_path / "site" / "record.html").read_text(encoding="utf-8")
    assert report == {"date": "2026-09-23", "pages": 4, "matches": 1}


def test_publish_refuses_when_forbidden_text_leaks(tmp_path: Path, monkeypatch):
    data, root = _data(tmp_path)
    monkeypatch.setattr("nutmeg.decision.day_publish.SCRUB_FORBIDDEN", ("A vs B",))
    with pytest.raises(PublishError):
        publish_day(data_dir=data, root=root, date="2026-09-23", out_dir=tmp_path / "site")
