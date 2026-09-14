"""单测国际欧赔血统 —— 换源后 source 必须逐场说实话，且承重点认得新源名。

``MarketSnapshot.source`` 既进快照 id，又是 ``anchor``/``day_regime`` 的优先级键。
2026-09-14 换源后 bold_odds 是 titan007(主)+apifootball(补缺) 的合并产物；整批贴
一个源名等于给判断层喂错血统，而把 apifootball 从优先级里删掉又会让历史快照的国际
锚静默消失。这两件事各钉一组。
"""

from __future__ import annotations

from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.fetch import unpack_euro_result
from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.decision.ontology import MarketSnapshot


def _snap(source: str, kind: str = "read_time", home: float = 0.5) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id=f"S-{source}-{kind}",
        match_id="M-1",
        taken_at="2026-09-14T12:00:00+08:00",
        kind=kind,
        source=source,
        fair={"had": {"home": home, "draw": 0.3, "away": 0.7 - home}},
        raw_odds={},
        lines={},
    )


def test_anchor_prefers_titan007_over_apifootball():
    prior, anchor = resolve_prior(
        [_snap("apifootball", home=0.40), _snap("titan007", home=0.55)], market="had"
    )
    assert anchor.source == "titan007"
    assert prior["home"] == 0.55


def test_anchor_still_finds_apifootball_on_historical_snapshots():
    """换源前的快照全是 apifootball——把它从优先级里删掉会让旧日子的国际锚消失。"""
    prior, anchor = resolve_prior(
        [_snap("sporttery", home=0.40), _snap("apifootball", home=0.55)], market="had"
    )
    assert anchor.source == "apifootball"
    assert prior["home"] == 0.55


def test_day_regime_reads_titan007_as_the_euro_side():
    from nutmeg.decision.day_regime import _EURO_SOURCES

    assert _EURO_SOURCES[0] == "titan007"
    assert "apifootball" in _EURO_SOURCES  # 历史快照仍要认


def test_source_by_match_labels_each_match_with_its_real_source():
    class _MW:
        fair_probability = {"home": 0.5, "draw": 0.3, "away": 0.2}

    bold = {"周一002": {"match_winner": _MW()}, "周一003": {"match_winner": _MW()}}
    snaps = euro_snapshot_from_bold_odds(
        bold, run_date="2026-09-14", taken_at="T", kind="read_time",
        source="apifootball",
        source_by_match={"周一002": "titan007"},   # 003 没给 → 回落
    )
    by_match = {s.match_id: s.source for s in snaps}
    assert by_match["M-2026-09-14-周一002"] == "titan007"
    assert by_match["M-2026-09-14-周一003"] == "apifootball"


def test_source_enters_the_snapshot_id_so_the_two_sources_never_collide():
    class _MW:
        fair_probability = {"home": 0.5, "draw": 0.3, "away": 0.2}

    bold = {"周一002": {"match_winner": _MW()}}
    a = euro_snapshot_from_bold_odds(
        bold, run_date="2026-09-14", taken_at="T", kind="closing",
        source="apifootball",
    )[0]
    b = euro_snapshot_from_bold_odds(
        bold, run_date="2026-09-14", taken_at="T", kind="closing",
        source="apifootball", source_by_match={"周一002": "titan007"},
    )[0]
    assert a.snapshot_id != b.snapshot_id


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
    from nutmeg.decision import fetch as fetch_mod

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
