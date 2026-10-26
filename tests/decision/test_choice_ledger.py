"""选择账（2026-10-26 Tier 4 #16）：同钱三列的算术与渲染。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.choice_ledger import (
    _shape,
    drop_c_form,
    issue_row,
    machine_form,
    machine_is_flat,
    render_choices,
    same_money_multiplier,
    settle_form,
)


class _Issue:
    """gym ZucaiIssue 的最小替身：settle_zucai 只读 prizes / results / void / issue。"""

    def __init__(self, results: str | None, per_note: float | None):
        self.issue = "26199"
        self.results = results
        self.void = set()
        self.prizes = {"renjiu": {"stake_amount": per_note}} if per_note else None


def test_same_money_multiplier_floors_and_never_below_one():
    assert same_money_multiplier(768, 256) == 3
    assert same_money_multiplier(100, 256) == 1       # 不足一注按一注
    assert same_money_multiplier(0, 256) == 1         # Jun 空仓期 ×1 作参考
    assert same_money_multiplier(500, 0) == 1


def test_shape_counts_singles_doubles_packs():
    assert _shape({"1": "3", "2": "31", "3": "310", "4": "0"}) == "2单1双1包"


def test_settle_form_scales_stake_and_payout_by_multiplier():
    form = {"faces": {str(i): "3" for i in range(1, 10)}, "stake_yuan": 2.0, "p_all": 0.05,
            "source": "draft.json"}
    results = " ".join(["3"] * 14)
    col = settle_form(form, _Issue(results, 1000.0), jun_stake=20)
    assert col["k"] == 10 and col["stake"] == 20 and col["payout"] == 10000.0
    assert col["net"] == 9980.0 and col["hits"] == 1 and col["shape"] == "9单"


def test_settle_form_without_official_prize_is_pending():
    form = {"faces": {str(i): "3" for i in range(1, 10)}, "stake_yuan": 2.0, "p_all": 0.05}
    col = settle_form(form, _Issue(None, None), jun_stake=0)
    assert col["payout"] is None and col["net"] is None
    assert settle_form(None, _Issue(None, None), jun_stake=0) == {"shape": None}


def test_machine_form_reads_draft_json_and_flat_marker(tmp_path: Path):
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    faces = {str(i): "3" for i in range(1, 10)}
    (zdir / "26199-draft.json").write_text(json.dumps({"candidates": [
        {"label": "初稿", "channel": "renjiu", "faces": faces, "stake_yuan": 2, "p_all": 0.1},
        {"label": "参考·丢光C档形", "channel": "renjiu", "rule": "drop_c",
         "faces": {**faces, "9": "310"}, "stake_yuan": 6, "p_all": 0.05},
    ]}), encoding="utf-8")
    (zdir / "26199-packet.md").write_text("…六条件许可胆 0 → 机器默认空仓…", encoding="utf-8")
    assert machine_form(tmp_path, "26199")["stake_yuan"] == 2.0
    assert drop_c_form(tmp_path, "26199")["source"] == "draft.json"
    assert machine_is_flat(tmp_path, "26199") is True
    assert machine_is_flat(tmp_path, "26198") is False
    assert machine_form(tmp_path, "26198") is None


def test_render_flat_machine_row_shows_zero_money_and_form():
    jun = {"n": 2, "stake": 640.0, "payout": 0.0, "pending": 0, "hits": 0, "p_sum": 0.13,
           "p_missing": 0, "ids": ["a", "b"], "net": -640.0}
    machine = {"shape": "1单8双", "stake": 512, "k": 1, "p": 0.18, "payout": 0.0, "net": -512.0,
               "hits": 0, "source": "draft.json"}
    drop_c = {"shape": "5单4包", "stake": 162, "k": 1, "p": 0.086, "payout": None, "net": None,
              "hits": None, "source": "重建"}
    row = issue_row("26144", jun=jun, machine=machine, drop_c=drop_c, flat=True)
    md = render_choices({"start": "26144", "end": None, "rows": [row]})
    expected = ("| 26144 | 2 张 ¥640 / P 0.13 / 中 0 / -640 | 空仓（1单8双 ¥512×0） | 0 "
                "| 18.0% | — | 0 | 5单4包·重建 ×1 | 162 | 8.6% | 待 | 待 |")
    assert expected in md
    assert "机器默认 0 期出票" in md and "退役形 1 期" in md
