"""Polymarket 公开接口的取数件（2026-10-09）。

设计稿 docs/superpowers/specs/2026-10-09-polymarket-attention-design.md。

单测一律注入 fetch(url, params) → JSON，不碰真网络。"""
from nutmeg.data.polymarket import (
    normalize_event,
    price_trend,
    series_events,
    soccer_series,
)


def test_soccer_series_keeps_only_whitelisted_league_codes():
    sports = [{"sport": "bun", "series": "10194"}, {"sport": "nba", "series": "1"},
              {"sport": "epl", "series": "10188"}]
    assert soccer_series(lambda url, params: sports) == {"bun": "10194", "epl": "10188"}


def test_series_events_pages_until_an_empty_batch_and_keeps_fixture_titles():
    pages = {0: [{"id": "1", "title": "A vs. B"}, {"id": "2", "title": "Will X happen?"}],
             100: [{"id": "3", "title": "C vs D"}], 200: []}
    seen = []

    def fetch(url, params):
        seen.append(params)
        return pages[params["offset"]]

    events = series_events(fetch, "10194", closed=False, end_min="2026-10-09",
                           end_max="2026-10-11")
    assert [e["id"] for e in events] == ["1", "3"]
    assert seen[0]["series_id"] == "10194" and seen[0]["closed"] == "false"
    assert seen[0]["end_date_min"] == "2026-10-09"


def test_normalize_event_takes_volume_and_best_quotes_per_market():
    ev = {"id": "1083681", "title": "BV Borussia 09 Dortmund vs. SV Werder Bremen",
          "endDate": "2026-10-09T18:30:00Z", "volume": 80268.2, "liquidity": 634612.9,
          "volume24hr": 20113.7,
          "markets": [{"question": "Will BV Borussia 09 Dortmund win on 2026-10-09?",
                       "bestBid": 0.74, "bestAsk": 0.75, "lastTradePrice": 0.75,
                       "clobTokenIds": "[\"tok-yes\", \"tok-no\"]"},
                      {"question": ("Will BV Borussia 09 Dortmund vs. SV Werder Bremen "
                                    "end in a draw?"),
                       "bestBid": "0.16", "bestAsk": "0.17", "clobTokenIds": "[\"d-yes\"]"}]}
    n = normalize_event(ev)
    assert n["id"] == "1083681" and n["end"] == "2026-10-09" and n["volume"] == 80268.2
    assert n["home"] == "BV Borussia 09 Dortmund" and n["away"] == "SV Werder Bremen"
    assert n["markets"][0] == {"question": ev["markets"][0]["question"], "bid": 0.74,
                               "ask": 0.75, "token": "tok-yes"}
    assert n["markets"][1]["bid"] == 0.16


def test_normalize_event_strips_a_league_prefix_and_rejects_non_fixtures():
    assert normalize_event({"id": "1", "title": "Bundesliga: Bayern Munich vs. Bayer Leverkusen",
                            "endDate": "2025-01-01", "markets": []})["home"] == "Bayern Munich"
    assert normalize_event({"id": "2", "title": "Will Messi play?", "markets": []}) is None


def test_price_trend_returns_first_and_last_point():
    history = {"history": [{"t": 1, "p": 0.715}, {"t": 2, "p": 0.73}, {"t": 3, "p": 0.745}]}
    assert price_trend(lambda url, params: history, "tok") == (0.715, 0.745)
    assert price_trend(lambda url, params: {"history": []}, "tok") == (None, None)


def test_normalize_event_drops_side_markets_of_the_same_fixture():
    """同一场有主事件和「- More Markets / - Halftime Result …」附加盘。

    英超 1,544 条只有 432 场。"""
    assert normalize_event({"id": "1", "title": "Liverpool vs. Manchester United - More Markets",
                            "endDate": "2025-10-19", "markets": []}) is None
    assert normalize_event({"id": "2", "title": "Paris Saint-Germain vs. Lyon",
                            "endDate": "2025-10-19", "markets": []})["home"] == \
        "Paris Saint-Germain"


def test_normalize_event_drops_same_title_sub_events_by_slug_suffix():
    """2026-10-09 实测：法甲同一场 10 个事件标题全一样，子事件只在 slug 日期后带后缀。"""
    main = {"id": "1083680", "title": "Racing Club de Lens vs. Olympique Lyonnais",
            "slug": "fl1-rcl-lyo-2026-10-09", "endDate": "2026-10-09", "markets": []}
    assert normalize_event(main)["home"] == "Racing Club de Lens"
    for suffix in ("halftime-result", "exact-score", "more-markets", "total-corners"):
        assert normalize_event({**main, "slug": f"fl1-rcl-lyo-2026-10-09-{suffix}"}) is None


def test_soccer_whitelist_uses_polymarkets_own_codes():
    from nutmeg.data.polymarket import SOCCER_CODES

    assert {"fr2", "itsb", "es2", "unl", "fl1", "swe", "nor"} <= SOCCER_CODES
    assert "fl2" not in SOCCER_CODES                  # 法乙在 Polymarket 是 fr2
