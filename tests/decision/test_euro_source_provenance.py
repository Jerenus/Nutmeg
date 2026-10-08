"""单测国际欧赔血统 —— 换源后 source 必须逐场说实话，且承重点认得新源名。

``MarketSnapshot.source`` 既进快照 id，又是 ``anchor``/``day_regime`` 的优先级键。
2026-09-14 换源后 bold_odds 是 titan007(主)+apifootball(补缺) 的合并产物；整批贴
一个源名等于给判断层喂错血统，而把 apifootball 从优先级里删掉又会让历史快照的国际
锚静默消失。这两件事各钉一组。
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


def test_apifootball_is_not_called_when_titan007_covers_the_board(monkeypatch):
    """懒备源：titan007 全覆盖时不得唤醒 API-Football。

    ``bold_odds`` 的下游一律只读 ``match_winner``，AF 补的 ``over_under`` 从无消费者；
    为一份没人读的盘口每天烧掉本就只有 100 次的配额是纯浪费。
    """
    from nutmeg.decision import fetch as fetch_mod

    value = {
        "matchInfoList": [
            {
                "businessDate": "2026-09-14",
                "subMatchList": [
                    {"matchNumStr": "周一002", "matchStatus": "Selling",
                     "businessDate": "2026-09-14"},
                ],
            }
        ]
    }
    called: list[str] = []
    monkeypatch.setattr(
        "nutmeg.services.jczq_titan007_odds.collect_bold_odds_titan007_live",
        lambda v, run_date: {"周一002": {"match_winner": object()}},
    )
    monkeypatch.setattr(
        "nutmeg.services.jczq_apifootball_odds.collect_bold_odds_apifootball_live",
        lambda v, run_date: called.append("af") or {},
    )
    merged, provenance = fetch_mod._default_euro_fetcher(value, "2026-09-14")
    assert called == [], "titan007 全覆盖时不该调 API-Football"
    assert provenance == {"周一002": "titan007"}


def test_apifootball_is_called_only_for_the_matches_titan007_missed(monkeypatch):
    """漏场唤醒备源 + 血统正确标注 —— **仅在备源被显式开启时**。

    2026-09-14 用户裁定「切」后备源默认关闭（实测 08:00 跑时 titan007 板面未铺开
    → 每天唤醒 → 免费档配额耗尽 → 自 09-01 起 164 次 429，**一场都没补上**）。
    本条的两层意图（漏场判定、血统标注）在开关打开时依然成立，故改测 opt-in 路径。
    默认关闭的行为由 `tests/decision/test_fetch.py` 的三条钉住。
    """
    from nutmeg.decision import fetch as fetch_mod

    monkeypatch.setenv("NUTMEG_JCZQ_APIFOOTBALL_FALLBACK", "1")

    value = {
        "matchInfoList": [
            {
                "businessDate": "2026-09-14",
                "subMatchList": [
                    {"matchNumStr": "周一002", "matchStatus": "Selling",
                     "businessDate": "2026-09-14"},
                    {"matchNumStr": "周一003", "matchStatus": "Selling",
                     "businessDate": "2026-09-14"},
                    # 次日场：不算今天漏的，不得据此唤醒备源
                    {"matchNumStr": "周二001", "matchStatus": "Selling",
                     "businessDate": "2026-09-15"},
                ],
            }
        ]
    }
    called: list[str] = []
    monkeypatch.setattr(
        "nutmeg.services.jczq_titan007_odds.collect_bold_odds_titan007_live",
        lambda v, run_date: {"周一002": {"match_winner": object()}},
    )
    monkeypatch.setattr(
        "nutmeg.services.jczq_apifootball_odds.collect_bold_odds_apifootball_live",
        lambda v, run_date: (called.append("af")
                             or {"周一003": {"match_winner": object()}}),
    )
    merged, provenance = fetch_mod._default_euro_fetcher(value, "2026-09-14")
    assert called == ["af"]
    assert provenance == {"周一002": "titan007", "周一003": "apifootball"}


def test_next_day_match_alone_never_wakes_the_fallback(monkeypatch):
    """**次日场不算今天漏的。** 一份 sporttery 快照含多个业务日，不按 businessDate
    过滤会把次日场当成今天的缺口，白白唤醒备源——即使备源被显式开启也不许。

    此前该纪律只写在注释里：原测试中 `周一003` 本就缺失，备源无论如何都会被唤醒，
    次日场那一条断言实际上从未被执行到。
    """
    from nutmeg.decision import fetch as fetch_mod

    monkeypatch.setenv("NUTMEG_JCZQ_APIFOOTBALL_FALLBACK", "1")
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
    called: list[str] = []
    monkeypatch.setattr(
        "nutmeg.services.jczq_titan007_odds.collect_bold_odds_titan007_live",
        lambda v, run_date: {"周一002": {"match_winner": object()}},
    )
    monkeypatch.setattr(
        "nutmeg.services.jczq_apifootball_odds.collect_bold_odds_apifootball_live",
        lambda v, run_date: called.append("af") or {},
    )
    _, provenance = fetch_mod._default_euro_fetcher(value, "2026-09-14")
    assert called == [], "次日场被当成今天的缺口了"
    assert provenance == {"周一002": "titan007"}
