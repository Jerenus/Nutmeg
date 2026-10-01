import json
from pathlib import Path

from nutmeg.gym.prizes import build_prize_cache, load_prizes

ITEM = {"lotteryDrawNum": "26127", "lotteryDrawTime": "2026-09-18 21:00:00",
        "lotterySaleEndtime": "2026-09-16 17:30:00",
        "lotteryDrawResult": "3 3 0 0 3 3 1 3 3 0 3 0 3 *",
        "totalSaleAmount": "15,520,204", "totalSaleAmountRj": "13,999,718",
        "prizeLevelList": [{"prizeLevel": "一等奖", "stakeCount": "401", "stakeAmount": "17,339"},
                           {"prizeLevel": "二等奖", "stakeCount": "9,340", "stakeAmount": "319"}],
        "prizeLevelListRj": [{"prizeLevel": "任选9场", "stakeCount": "50,908",
                              "stakeAmount": "176"}]}
BAD = {"lotteryDrawNum": "26135", "lotteryDrawResult": "", "prizeLevelList": [],
       "prizeLevelListRj": []}


def test_cache_parses_void_matches_and_comma_numbers(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    path = build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [ITEM, BAD]}},
                             page_size=2)
    doc = json.loads(path.read_text(encoding="utf-8"))
    row = doc["issues"]["26127"]
    assert row["results"] == "3 3 0 0 3 3 1 3 3 0 3 0 3 *" and row["void_matches"] == [14]
    assert row["renjiu"] == {"stake_count": 50908, "stake_amount": 176.0}
    assert row["sfc_first"]["stake_amount"] == 17339.0 and row["sfc_second"]["stake_count"] == 9340
    assert row["sale_amount_rj"] == 13999718.0
    assert "26135" not in doc["issues"]                     # 未开奖不入缓存
    assert load_prizes(zdir)["26127"]["draw_date"] == "2026-09-18"


def test_cache_merges_incrementally_and_newer_fetch_wins(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [ITEM]}}, page_size=1)
    newer = {**ITEM, "lotteryDrawNum": "26128",
             "lotteryDrawResult": "3 1 0 3 1 0 3 1 0 3 1 0 3 1"}
    revised = {**ITEM, "prizeLevelListRj": [{"prizeLevel": "任选9场", "stakeCount": "1",
                                              "stakeAmount": "999"}]}
    build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [newer, revised]}},
                      page_size=2)
    prizes = load_prizes(zdir)
    assert set(prizes) == {"26127", "26128"}
    assert prizes["26127"]["renjiu"]["stake_amount"] == 999.0
    assert prizes["26128"]["void_matches"] == []


def test_load_prizes_without_cache_is_empty(tmp_path: Path) -> None:
    assert load_prizes(tmp_path) == {}
