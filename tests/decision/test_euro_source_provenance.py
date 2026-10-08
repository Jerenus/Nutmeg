"""单测国际欧赔血统 —— 换源后 source 必须逐场说实话，且承重点认得新源名。

``MarketSnapshot.source`` 既进快照 id，又是 ``anchor``/``day_regime`` 的优先级键。
2026-09-14 换源后 titan007 为主、apifootball 补缺；2026-10-08 备源删除后只剩 titan007，
历史快照里的 apifootball 源名保持原样，不改写。
"""

from __future__ import annotations

from nutmeg.decision.fetch import unpack_euro_result


def test_unpack_euro_result_accepts_both_shapes():
    """生产 fetcher 回元组，测试替身回纯 dict——两种都要收。"""
    assert unpack_euro_result({"周一002": {}}) == ({"周一002": {}}, {})
    assert unpack_euro_result(({"周一002": {}}, {"周一002": "titan007"})) == (
        {"周一002": {}}, {"周一002": "titan007"},
    )
    assert unpack_euro_result(None) == ({}, {})


def test_next_day_match_is_not_reported_as_a_titan007_miss(monkeypatch, caplog):
    """**次日场不算今天漏的。** 一份 sporttery 快照含多个业务日，不按 businessDate 过滤会把
    次日场当成今天的缺口（备源时代会白白唤醒备源，现在会误报「漏场」）。"""
    import logging

    from nutmeg.decision import fetch as fetch_mod

    value = {
        "matchInfoList": [
            {
                "businessDate": "2026-09-14",
                "subMatchList": [
                    {"matchNumStr": "周一002", "matchStatus": "Selling",
                     "businessDate": "2026-09-14"},
                    {"matchNumStr": "周二001", "matchStatus": "Selling",
                     "businessDate": "2026-09-15"},
                ],
            }
        ]
    }
    monkeypatch.setattr(
        "nutmeg.services.jczq_titan007_odds.collect_bold_odds_titan007_live",
        lambda v, run_date: {"周一002": {"match_winner": object()}},
    )
    with caplog.at_level(logging.WARNING, logger="nutmeg.decision.fetch"):
        _, provenance = fetch_mod._default_euro_fetcher(value, "2026-09-14")
    assert "漏" not in caplog.text, "次日场被当成今天的缺口了"
    assert provenance == {"周一002": "titan007"}
