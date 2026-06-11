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
