import json

from nutmeg.decision.overrides import record_override
from nutmeg.decision.signals import build_signals, render_signals

DAY = "2026-09-26"
PRIOR = {"home": 0.745, "draw": 0.168, "away": 0.087}
TILT7 = {"face": "1", "expires_if": "x", "evidence": [
    {"tier": "official", "kind": "goalkeeper_change", "pp": 4, "source": "s",
     "captured_at": "2026-09-26T08:19:00+08:00"},
    {"tier": "confirmed_structural", "kind": "anchor_integrity_fail", "pp": 3, "source": "s",
     "captured_at": "2026-09-26T08:19:00+08:00"}]}


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _setup(tmp_path):
    day_dir = tmp_path / "jczq" / "daily" / DAY
    _write(day_dir / "jczq-legs-base.json", {"legs": {"周六011": {
        "match_id": "j-011", "name": "冰岛-爱沙尼亚", "kickoff_bj": "2026-09-27T00:00:00+08:00",
        "fair": PRIOR}}})
    _write(day_dir / "reads.json", [{"match_id": "j-011", "prior": PRIOR,
                                     "belief": {"home": 0.725, "draw": 0.188, "away": 0.087}}])
    _write(day_dir / "research-周六011.json", {
        "name": "冰岛-爱沙尼亚", "confidence": 3,
        "stance": {"face": "3", "structure": "double", "cover": "1", "tilt": TILT7},
        "strength_balance": {"verdict": "home_edge", "underdog_path": {"strength": "real"},
                             "events": [{"event": "门将肾脏手术", "priced_in": False}]}})
    record_override(day_dir / "research-周六011.json", tilt=None, note="已定价",
                    at="2026-09-26T14:15:00+08:00", judge="claude", prior=PRIOR)
    _write(tmp_path / "jczq" / "jc-results.json", {DAY: {"周六011": {"ft_home": 1, "ft_away": 1}}})
    zdir = tmp_path / "zucai"
    _write(zdir / "26133-issue.json", {"issue_id": "26133", "sale_deadline": f"{DAY} 20:30",
                                       "matches": []})
    _write(zdir / "26133-store-ids.json", {
        "4": {"match_no": 4, "match_id": "z-4", "name": "冰岛-爱沙尼", "fair": PRIOR},
        "1": {"match_no": 1, "match_id": "z-1", "name": "中国-新西兰",
              "fair": {"home": 0.36, "draw": 0.28, "away": 0.36}}})
    _write(zdir / "26133-channel-map.auto.json", {"j-011": 4})
    _write(zdir / "26133-research-m4.json", {"name": "冰岛", "confidence": 3,
                                             "stance": {"face": "3", "structure": "single"}})
    return tmp_path


def test_signals_keep_the_research_signal_the_main_loop_cut_and_score_it(tmp_path):
    rows = build_signals(day=DAY, data_dir=_setup(tmp_path))
    iceland = next(r for r in rows if r["key"] == "周六011")
    assert iceland["override"]["note"] == "已定价"
    assert round(iceland["research"]["shift"]["draw"], 1) == 7.0
    assert iceland["research"]["unpriced"] == ["门将肾脏手术"]
    assert iceland["outcome"] == "1"
    assert iceland["brier_research"] < iceland["brier_final"]      # 砍掉 +7 是亏的


def test_signals_pair_both_channels_and_flag_the_disagreement(tmp_path):
    rows = build_signals(day=DAY, data_dir=_setup(tmp_path))
    iceland = next(r for r in rows if r["key"] == "周六011")
    assert iceland["paired"]["key"] == "足彩26133-04"
    assert any("结构" in item for item in iceland["disagreement"])
    assert any(r["key"] == "足彩26133-01" for r in rows)            # 足彩独有场次也进面板
    text = render_signals(rows, day=DAY)
    assert "主循环改判了研究的信号" in text and "同场两份研究打架" in text
