# tests/decision/test_zucai_official.py
import json

import pytest

from nutmeg.decision.zucai_official import (
    fetch_official,
    fetch_renjiu_history,
    parse_draw,
    parse_renjiu_history_item,
    record_official_result,
)

# 26102 官方真实数据(2026-08-10 开奖,已用 API 实测核对)作 fixture
_ITEM = {
    "lotteryDrawNum": "26102",
    "lotteryDrawTime": "2026-08-10",
    "lotteryDrawResult": "3 0 3 3 1 3 1 3 0 0 1 3 1 0",
    "prizeLevelListRj": [{"prizeLevel": "任选9场", "stakeCount": "408", "stakeAmount": "21,018"}],
    "prizeLevelList": [
        {"prizeLevel": "一等奖", "stakeCount": "2", "stakeAmount": "4,567,569"},
        {"prizeLevel": "二等奖", "stakeCount": "61", "stakeAmount": "48,401"},
    ],
    "totalSaleAmountRj": "13,399,134",
}


def test_parse_draw_official_string_is_the_authority():
    d = parse_draw(_ITEM)
    assert d.results["1"] == "3" and d.results["14"] == "0" and len(d.results) == 14
    assert d.renjiu == {"stake_count": 408, "stake_amount": 21018.0}
    assert d.sfc_first["stake_amount"] == 4567569.0
    assert d.sale_amount_rj == 13399134.0


def test_parse_renjiu_history_keeps_bonus_when_results_contain_cancellations():
    item = {
        "lotteryDrawNum": "26106",
        "lotteryDrawTime": "2026-08-18",
        "lotteryDrawResult": "1 3 1 3 * 1 3 3 0 * 0 0 3 3",
        "prizeLevelListRj": [{
            "prizeLevel": "任选9场",
            "stakeCount": "2,028",
            "stakeAmount": "4,347",
        }],
        "totalSaleAmountRj": "13,777,502",
    }

    row = parse_renjiu_history_item(item)

    assert row.issue == "26106"
    assert row.stake_count == 2028
    assert row.stake_amount == 4347.0
    assert abs(row.pool_implied_bonus - 4347.93) < 0.01


def test_parse_renjiu_history_accepts_26111_floor_rounding():
    row = parse_renjiu_history_item({
        "lotteryDrawNum": "26111",
        "lotteryDrawTime": "2026-08-28",
        "prizeLevelListRj": [{
            "prizeLevel": "任选9场",
            "stakeCount": "43,365",
            "stakeAmount": "215",
        }],
        "totalSaleAmountRj": "14,617,834",
    })

    assert row.issue == "26111"
    assert row.payout_consistent_with_return_rate()


@pytest.mark.parametrize(
    "changes",
    [
        {"prizeLevelListRj": []},
        {"prizeLevelListRj": [{"stakeCount": "0", "stakeAmount": "100"}]},
        {"totalSaleAmountRj": "0"},
    ],
)
def test_parse_renjiu_history_rejects_missing_or_nonpositive_facts(changes):
    with pytest.raises(ValueError, match="任九历史"):
        parse_renjiu_history_item({**_ITEM, **changes})


def test_fetch_renjiu_history_uses_official_game_90_payload():
    seen = {}

    def fetcher(url):
        seen["url"] = url
        return {"value": {"list": [_ITEM]}}

    rows = fetch_renjiu_history(fetcher=fetcher, page_size=37)

    assert "gameNo=90" in seen["url"] and "pageSize=37" in seen["url"]
    assert [row.issue for row in rows] == ["26102"]


def test_parse_rejects_malformed_result_string():
    """赛果串不是 14 个合法码必须抛错——宁死不猜,静默降级是最贵的坏。"""
    bad = dict(_ITEM, lotteryDrawResult="3 0 3")
    with pytest.raises(ValueError):
        parse_draw(bad)
    bad2 = dict(_ITEM, lotteryDrawResult="3 0 3 3 1 3 1 3 0 0 1 3 1 X")
    with pytest.raises(ValueError):
        parse_draw(bad2)


def test_aet_guard_source_never_touches_goals():
    """D3 守卫:本模块不得引用 API-Football 的 goals 字段(含加时)。

    2026-08-11 博德实测:90' 2-2 / goals 3-2 —— 用 goals 结算会把平局记成主胜。
    官方 lotteryDrawResult 是 90 分钟口径,是唯一权威。
    """
    import inspect

    import nutmeg.decision.zucai_official as mod
    src = inspect.getsource(mod)
    assert "api-sports" not in src.lower()
    assert '"goals"' not in src and "['goals']" not in src


def test_fetch_returns_none_when_not_drawn():
    payload = {"value": {"list": [_ITEM]}}
    assert fetch_official("26103", fetcher=lambda _u: payload) is None
    got = fetch_official("26102", fetcher=lambda _u: payload)
    assert got and got.issue == "26102"


def test_record_official_result_upserts_the_draw_string(tmp_path):
    (tmp_path / "official-results.json").write_text(
        json.dumps({"26101": "3 3 3 3 3 3 3 3 3 3 3 3 3 3"}), "utf-8")
    d = parse_draw(_ITEM)

    record_official_result(d, tmp_path)
    record_official_result(d, tmp_path)

    doc = json.loads((tmp_path / "official-results.json").read_text("utf-8"))
    assert doc == {"26101": "3 3 3 3 3 3 3 3 3 3 3 3 3 3",
                   "26102": "3 0 3 3 1 3 1 3 0 0 1 3 1 0"}


def test_record_official_result_creates_the_file(tmp_path):
    record_official_result(parse_draw(_ITEM), tmp_path)
    doc = json.loads((tmp_path / "official-results.json").read_text("utf-8"))
    assert doc["26102"].split()[4] == "1"
