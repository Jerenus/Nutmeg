"""Polymarket 关注度：对号、快照、人群层字段、回补、语料挂载（2026-10-09 设计稿）。"""
import json
from pathlib import Path

from nutmeg.decision.crowd_polymarket import (
    Namer,
    attach_polymarket,
    attention_for_issue,
    board_rows,
    faces_from_markets,
    match_event,
    side_matches,
    write_snapshot,
)

NAMER = Namer(cn2en={"多特": "Borussia Dortmund", "不来梅": "Werder Bremen",
                     "西汉姆联": "West Ham", "巡游者": "QPR", "哥德堡": "IFK Goteborg"},
              resolve=lambda name: None, seed_en={})


def _event(eid, home, away, end="2026-10-09", volume=80000.0, quotes=None):
    q = quotes or {"home": (0.74, 0.75), "draw": (0.16, 0.17), "away": (0.10, 0.11)}
    return {"id": eid, "title": f"{home} vs. {away}", "end": end, "home": home, "away": away,
            "volume": volume, "liquidity": 1.0, "volume24hr": 2.0, "markets": [
                {"question": f"Will {home} win on {end}?", "bid": q["home"][0], "ask": q["home"][1],
                 "token": f"{eid}-h"},
                {"question": f"Will {home} vs. {away} end in a draw?", "bid": q["draw"][0],
                 "ask": q["draw"][1], "token": f"{eid}-d"},
                {"question": f"Will {away} win on {end}?", "bid": q["away"][0], "ask": q["away"][1],
                 "token": f"{eid}-a"}]}


def test_side_matching_uses_tokens_accents_and_acronyms():
    assert side_matches(["Borussia Dortmund"], "BV Borussia 09 Dortmund")
    assert side_matches(["QPR"], "Queens Park Rangers FC")
    assert side_matches(["IFK Goteborg"], "IFK Göteborg")
    assert not side_matches(["West Ham"], "Westerlo")
    assert not side_matches([], "Anything FC")


def test_match_event_needs_both_sides_a_unique_hit_and_a_date_within_a_day():
    events = [_event("1", "BV Borussia 09 Dortmund", "SV Werder Bremen"),
              _event("2", "West Ham United FC", "Queens Park Rangers FC", end="2026-10-08")]
    assert match_event(NAMER, ["多特"], ["不来梅"], "2026-10-10", events)["id"] == "1"
    assert match_event(NAMER, ["西汉姆联"], ["巡游者"], "2026-10-09", events)["id"] == "2"
    assert match_event(NAMER, ["多特"], ["巡游者"], "2026-10-09", events) is None
    assert match_event(NAMER, ["多特"], ["不来梅"], "2026-10-12", events) is None
    twice = events + [_event("3", "Borussia Dortmund", "Werder Bremen")]
    assert match_event(NAMER, ["多特"], ["不来梅"], "2026-10-09", twice) is None   # 不唯一不猜


def test_faces_are_assigned_by_the_team_named_in_each_market_question():
    ev = _event("1", "BV Borussia 09 Dortmund", "SV Werder Bremen")
    faces = faces_from_markets(ev, ["Borussia Dortmund"], ["Werder Bremen"])
    assert faces["home"]["mid"] == 0.745 and faces["draw"]["mid"] == 0.165
    assert faces["away"]["token"] == "1-a"


def test_board_rows_normalise_compare_with_market_and_rank_by_volume():
    events = [_event("1", "BV Borussia 09 Dortmund", "SV Werder Bremen", volume=80000.0),
              _event("2", "West Ham United FC", "Queens Park Rangers FC", volume=3800.0,
                     quotes={"home": (0.66, 0.67), "draw": (0.19, 0.20), "away": (0.14, 0.15)})]
    matches = [{"key": "2", "home": ["多特"], "away": ["不来梅"],
                "kickoff": "2026-10-10T02:30:00+08:00",
                "fair": {"home": 0.70, "draw": 0.17, "away": 0.13}},
               {"key": "1", "home": ["西汉姆联"], "away": ["巡游者"],
                "kickoff": "2026-10-10T03:00:00+08:00",
                "fair": {"home": 0.62, "draw": 0.21, "away": 0.17}},
               {"key": "5", "home": ["马拉加"], "away": ["西班人"],
                "kickoff": "2026-10-10T03:00:00+08:00",
                "fair": {"home": 0.35, "draw": 0.30, "away": 0.35}}]
    rows = board_rows(NAMER, matches, events)
    assert set(rows) == {"1", "2"}                        # 马拉加对不上：如实缺失
    dort = rows["2"]
    assert dort["rank"] == 1 and rows["1"]["rank"] == 2
    assert abs(sum(dort["probs"].values()) - 1) < 1e-9
    assert dort["vs_market_pp"]["home"] > 0 and dort["kickoff"].startswith("2026-10-10T02:30")


def test_board_rows_read_money_direction_from_trade_flow_and_flag_lopsided_books():
    """资金去向（2026-10-18 Jun）：钱去了哪支队 = 逐笔 买Yes−卖Yes−买No 最大的那一面；
    「富勒姆型」= 有量、单一市场占事件 ≥80%、三面价不动。"""
    ev = _event("1", "AFC Bournemouth", "Sunderland AFC", end="2026-10-18", volume=31000.0)
    for m, (vol, cid) in zip(ev["markets"], ((3000.0, "c-h"), (1000.0, "c-d"), (27000.0, "c-a")),
                             strict=True):
        m["volume"], m["condition_id"] = vol, cid
    flows = {"c-h": {"buy_yes": 1000.0, "buy_no": 600.0, "sell_yes": 100.0, "sell_no": 0.0,
                     "n": 90, "biggest": None},
             "c-d": {"buy_yes": 300.0, "buy_no": 0.0, "sell_yes": 0.0, "sell_no": 0.0,
                     "n": 43, "biggest": None},
             "c-a": {"buy_yes": 1900.0, "buy_no": 5600.0, "sell_yes": 3200.0, "sell_no": 0.0,
                     "n": 109, "biggest": {"side": "SELL", "outcome": "Yes", "usd": 3200.0,
                                           "price": 0.26, "who": "x"}}}
    matches = [{"key": "1", "home": ["伯恩茅斯"], "away": ["桑德兰"],
                "kickoff": "2026-10-18T21:00:00+08:00",
                "fair": {"home": 0.45, "draw": 0.27, "away": 0.28}}]
    namer = Namer(cn2en={"伯恩茅斯": "Bournemouth", "桑德兰": "Sunderland"},
                  resolve=lambda n: None, seed_en={})
    rows = board_rows(namer, matches, [ev], trend=lambda token: (0.46, 0.46),
                      flow=lambda cid: flows[cid])
    row = rows["1"]
    assert row["faces"]["away"]["volume"] == 27000.0 and row["flow"]["away"]["buy_no"] == 5600.0
    # 客市场的钱是反桑德兰的：客面净 −6900 → 反桑德兰；主面净 +300 不到 $1k 不读方向
    assert row["money_to"] == {"face": None, "usd": None, "against": "away",
                               "against_usd": -6900.0}
    assert row["lopsided"] is True                       # 客市场占 87%，三面价 0.0
    quiet = board_rows(namer, matches, [ev], trend=lambda token: (0.40, 0.46))
    assert "flow" not in quiet["1"] and quiet["1"]["lopsided"] is False


def test_write_snapshot_appends(tmp_path: Path):
    path = tmp_path / "zucai" / "26136-polymarket.json"
    write_snapshot(path, {"issue": "26136"}, {"2": {"volume": 1.0}}, fetched_at="t1")
    write_snapshot(path, {"issue": "26136"}, {"2": {"volume": 2.0}}, fetched_at="t2")
    doc = json.loads(path.read_text("utf-8"))
    assert [s["fetched_at"] for s in doc["snapshots"]] == ["t1", "t2"]


def test_attention_for_issue_reads_the_last_snapshot_as_volume_k_and_rank(tmp_path: Path):
    zdir = tmp_path / "zucai"
    write_snapshot(zdir / "26136-polymarket.json", {"issue": "26136"},
                   {"2": {"volume": 80268.0, "rank": 1}, "12": {"volume": 46743.0, "rank": 2}},
                   fetched_at="t1")
    assert attention_for_issue(zdir, "26136") == {2: (80.268, 1), 12: (46.743, 2)}
    assert attention_for_issue(zdir, "99999") == {}


def test_attach_hangs_the_last_pre_kickoff_snapshot_row_on_corpus_rows(tmp_path: Path):
    zdir = tmp_path / "zucai"
    row = {"volume": 80268.0, "kickoff": "2026-10-10T02:30:00+08:00"}
    write_snapshot(zdir / "26136-polymarket.json", {"issue": "26136"}, {"2": row},
                   fetched_at="2026-10-09T12:00:00+08:00")
    write_snapshot(zdir / "26136-polymarket.json", {"issue": "26136"},
                   {"2": {**row, "volume": 99999.0}}, fetched_at="2026-10-10T05:00:00+08:00")
    rows = [{"src": "zucai", "key": "26136-2"}, {"src": "zucai", "key": "26136-3"}]
    assert attach_polymarket(rows, tmp_path) == 1
    assert rows[0]["polymarket"]["volume"] == 80268.0       # 开球后的快照不算
    assert "polymarket" not in rows[1]


def _raw(eid, home, away, end, volume, closed=False):
    return {"id": eid, "title": f"{home} vs. {away}", "endDate": f"{end}T18:30:00Z",
            "volume": volume, "liquidity": 10.0, "volume24hr": 1.0, "closed": closed,
            "markets": [
                {"question": f"Will {home} win on {end}?", "bestBid": 0.74, "bestAsk": 0.75,
                 "clobTokenIds": f"[\"{eid}-h\"]"},
                {"question": f"Will {home} vs. {away} end in a draw?", "bestBid": 0.16,
                 "bestAsk": 0.17, "clobTokenIds": f"[\"{eid}-d\"]"},
                {"question": f"Will {away} win on {end}?", "bestBid": 0.10, "bestAsk": 0.11,
                 "clobTokenIds": f"[\"{eid}-a\"]"}]}


def _fake_fetch(open_events, closed_events=()):
    def fetch(url, params):
        if url.endswith("/sports"):
            return [{"sport": "bun", "series": "1"}]
        if url.endswith("/events"):
            if params.get("offset"):
                return []
            return list(closed_events if params["closed"] == "true" else open_events)
        if url.endswith("/prices-history"):
            return {"history": [{"p": 0.70}, {"p": 0.745}]}
        raise AssertionError(url)
    return fetch


def _issue(data: Path):
    zdir = data / "zucai"
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / "26136-issue.json").write_text(json.dumps({
        "issue_id": "26136", "sale_deadline": "2026-10-09 22:00", "matches": [
            {"match_no": 2, "home_team": "多特", "away_team": "不来梅",
             "kickoff_bj": "2026-10-10 02:30"}]}, ensure_ascii=False), encoding="utf-8")
    (zdir / "26136-store-ids.json").write_text(json.dumps({"2": {
        "match_id": "m2", "fair": {"home": 0.70, "draw": 0.17, "away": 0.13}}}), encoding="utf-8")


def test_snapshot_issue_writes_rows_with_trend_for_liquid_matches(tmp_path: Path):
    from nutmeg.decision.crowd_polymarket import snapshot_issue

    _issue(tmp_path)
    fetch = _fake_fetch([_raw("e1", "BV Borussia 09 Dortmund", "SV Werder Bremen",
                              "2026-10-09", 80268.0)])
    path = snapshot_issue(tmp_path, "26136", fetch=fetch, now="2026-10-09T12:00:00+08:00",
                          namer=NAMER)
    snap = json.loads(path.read_text("utf-8"))["snapshots"][-1]
    row = snap["rows"]["2"]
    assert row["rank"] == 1 and row["trend_pp"]["home"] == 4.5
    assert snap["fetched_at"] == "2026-10-09T12:00:00+08:00"


def test_backfill_matches_closed_events_and_marks_the_snapshot_source(tmp_path: Path):
    from nutmeg.decision.crowd_polymarket import backfill

    _issue(tmp_path)
    fetch = _fake_fetch([], [_raw("e1", "BV Borussia 09 Dortmund", "SV Werder Bremen",
                                  "2026-10-09", 123456.0, closed=True)])
    out = backfill(tmp_path, ["26136"], fetch=fetch, now="2026-10-11T09:00:00+08:00",
                   namer=NAMER)
    assert out == {"26136": 1}
    snap = json.loads((tmp_path / "zucai" / "26136-polymarket.json").read_text("utf-8"))[
        "snapshots"][-1]
    assert snap["source"] == "closed_backfill" and snap["rows"]["2"]["volume"] == 123456.0
    assert (tmp_path / "zucai" / "polymarket-closed.json").exists()     # 缓存，重跑不再全量拉


def test_every_keyword_must_match_exactly_or_as_a_prefix():
    """2026-10-09 实测：「Lyon」对「Olympique Lyonnais」漏配；
    放宽到前缀又不能让 West Ham 配上 Westerlo，
    也不能让曼城/曼联互配——所以我方每个关键词都要命中（相同或 ≥4 字母前缀）。"""
    assert side_matches(["Lyon"], "Olympique Lyonnais")
    assert not side_matches(["West Ham"], "Westerlo")
    assert not side_matches(["Manchester United"], "Manchester City FC")
    assert side_matches(["Manchester United"], "Manchester United FC")


def test_board_matches_fall_back_to_the_zgzcw_snapshot_without_an_issue_file(tmp_path: Path):
    """期次文件只从 26070 起有；26035–26069 的人群回放只能用 zgzcw 快照里的队名与开球时间。"""
    from nutmeg.decision.crowd_polymarket import zucai_board_matches

    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26040-zgzcw.json").write_text(json.dumps({"snapshots": [{"fetched_at": "t", "raw": {
        "matchInfo": [{"hostName": "多特", "hostNameFull": "多特蒙德", "guestName": "不来梅",
                       "guestNameFull": "不来梅", "gameStartDate": "2026-03-07 22:30:00",
                       "europeSp": "1.40 5.20 7.50"}]}}]}, ensure_ascii=False), encoding="utf-8")
    [m] = zucai_board_matches(tmp_path, "26040")
    assert m["key"] == "1" and m["home"] == ["多特", "多特蒙德"]
    assert m["kickoff"].startswith("2026-03-07 22:30") and abs(sum(m["fair"].values()) - 1) < 1e-9
