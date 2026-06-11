"""日报数据合成 + 「今日主线」确定性叙事(spec §5.3)。"""
from __future__ import annotations

from nutmeg.services.worldcup.report_data import (
    NARRATIVE_TEMPLATES,
    _signals_from,
    pick_narrative,
)


def test_templates_cover_all_keys() -> None:
    assert {"hot_board", "cold_board", "knockout", "prob_shift", "thin_board",
            "default"} <= set(NARRATIVE_TEMPLATES)


def test_pick_narrative_is_deterministic_and_keyed() -> None:
    sig = {"n_matches": 4, "hard_hot": 3, "stage": "group", "max_delta_pp": 2.0}
    a = pick_narrative(sig)
    assert a == pick_narrative(sig)
    assert "热门" in a            # hard_hot 占比 ≥ 0.5 → hot_board 模板


def test_pick_narrative_knockout_beats_hot() -> None:
    sig = {"n_matches": 2, "hard_hot": 2, "stage": "r16", "max_delta_pp": 1.0}
    assert "90 分钟" in pick_narrative(sig)


def test_pick_narrative_prob_shift() -> None:
    sig = {"n_matches": 2, "hard_hot": 0, "stage": "group", "max_delta_pp": 8.5}
    assert "重新定价" in pick_narrative(sig)


def test_signals_from_counts_only_b1_rows() -> None:
    """§D 雷达表的行同样以「| 周」开头 — 只数 B1 节内的行(真实 packet 格式)。"""
    packet = "\n".join([
        "## B. 盘面底座（引擎口径，无 generator 偏差）",
        "",
        "### B1 热度分层",
        "",
        "| 编号 | 对阵 | 最低 had | 热度 |",
        "|---|---|---|---|",
        "| 周四001 | 墨西哥 vs 南非 | 1.26 | 硬热(短赔) |",
        "| 周四002 | 韩国 vs 捷克 | 2.40 | coinflip |",
        "",
        "### B2 Poisson +EV 列表（raw，无 R25/F2/F3，edge ≥ +5%）",
        "",
        "## D. 机会雷达（多视角 · 挖不被注意的机会）",
        "",
        "| 场次 | 指向 | 信心 | 依据 |",
        "|---|---|---|---|",
        "| 周四002 韩国 vs 捷克 | **客胜** | 弱 | 反主胜 · 混战 |",
    ])
    sig = _signals_from(packet, None, None)
    assert sig["n_matches"] == 2
    assert sig["hard_hot"] == 1


def test_build_daily_report_loads_predictions_and_ledger(tmp_path) -> None:
    import json

    from nutmeg.services.worldcup.report_data import build_daily_report

    daily = tmp_path / "daily" / "2026-06-12"
    daily.mkdir(parents=True)
    (daily / "predictions.json").write_text(json.dumps({
        "date": "2026-06-12", "judge": "claude",
        "picks": [{"fixture": "A vs B", "judgment": "home", "score": "2-1",
                   "reason": "r", "confidence": 4}],
        "champion_pick": {"team": "Argentina", "reason": "x"},
        "opinion_ticket": None, "written_at": "t",
    }, ensure_ascii=False), encoding="utf-8")
    wc = tmp_path / "wc2026"
    wc.mkdir()
    (wc / "judge-ledger.jsonl").write_text(json.dumps({
        "date": "2026-06-11", "kind": "pick", "match_id": "M01",
        "judgment_hit": True, "score_hit": False, "baseline_hit": True,
        "upset_flag": False, "upset_hit": False, "pending": False,
    }) + "\n", encoding="utf-8")
    report = build_daily_report("2026-06-12", tmp_path)
    assert report.predictions is not None
    assert report.predictions.picks[0].judgment == "home"
    assert report.ledger_summary is not None
    assert report.ledger_summary.n_picks == 1
    assert len(report.ledger_yesterday) == 1
