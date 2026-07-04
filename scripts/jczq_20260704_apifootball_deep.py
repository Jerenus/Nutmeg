"""2026-07-04 — API-Football 深采（fixtures + predictions + injuries）.

用途: 给判读层补一个独立参考角度(球队近况/攻防强度/泊松对比/大小球提示/伤停),
只采数据+确定性摘要, 判断不烤进脚本。
UTC 口径: 今天 11 场全部落在 UTC 2026-07-04(北京 07-04 18:30 ~ 07-05 05:00)。
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parents[1]
load_dotenv(ROOT / ".env")

BASE = os.environ.get("NUTMEG_API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io").rstrip("/")
KEY = os.environ["NUTMEG_API_FOOTBALL_KEY"]
HEADERS = {"x-apisports-key": KEY}

# league_id: World Cup=1, K League 1=292, Veikkausliiga=244, Allsvenskan=113
LEAGUES = {1: "世界杯", 292: "韩职", 244: "芬超", 113: "瑞超"}
DATE = "2026-07-04"

# 竞彩编号 ←→ (联赛, 主队关键词) 映射（英文名匹配用小写子串）
BOARD = {
    "周六089": (1, ["canada"], ["morocco"]),
    "周六090": (1, ["paraguay"], ["france"]),
    "周六201": (292, ["anyang"], ["pohang"]),
    "周六202": (292, ["daejeon"], ["bucheon"]),
    "周六203": (292, ["jeonbuk"], ["gangwon"]),
    "周六204": (244, ["lahti"], ["gnistan"]),
    "周六205": (113, ["halmstad"], ["vasteras", "västerås"]),
    "周六206": (113, ["degerfors"], ["malmo", "malmö"]),
    "周六207": (244, ["seinajoen", "sjk"], ["tps"]),
    "周六208": (244, ["jaro"], ["ilves"]),
    "周六209": (244, ["vps", "vaasa"], ["mariehamn"]),
}


def get(path, **params):
    r = httpx.get(f"{BASE}/{path}", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print("API errors:", path, params, data["errors"])
    return data.get("response") or []


def match_board(fixtures):
    out = {}
    for num, (lg, hkeys, akeys) in BOARD.items():
        for fx in fixtures:
            if fx["league"]["id"] != lg:
                continue
            h = fx["teams"]["home"]["name"].lower()
            a = fx["teams"]["away"]["name"].lower()
            if any(k in h for k in hkeys) and any(k in a for k in akeys):
                out[num] = fx
                break
        if num not in out:
            print(f"⚠️ {num} 未匹配到 fixture")
    return out


def main():
    fixtures = []
    for lg in LEAGUES:
        fixtures += get("fixtures", date=DATE, league=lg, season=2026)
    print(f"fetched {len(fixtures)} fixtures for {sorted(LEAGUES)}")
    board = match_board(fixtures)

    out = {}
    for num, fx in board.items():
        fid = fx["fixture"]["id"]
        pred = get("predictions", fixture=fid)
        inj = get("injuries", fixture=fid)
        p = pred[0] if pred else {}
        out[num] = {
            "fixture_id": fid,
            "kickoff_utc": fx["fixture"]["date"],
            "venue": fx["fixture"].get("venue"),
            "teams": {"home": fx["teams"]["home"]["name"], "away": fx["teams"]["away"]["name"]},
            "predictions": {
                "winner": (p.get("predictions") or {}).get("winner"),
                "advice": (p.get("predictions") or {}).get("advice"),
                "percent": (p.get("predictions") or {}).get("percent"),
                "under_over": (p.get("predictions") or {}).get("under_over"),
                "goals": (p.get("predictions") or {}).get("goals"),
                "win_or_draw": (p.get("predictions") or {}).get("win_or_draw"),
                "comparison": p.get("comparison"),
            },
            "team_stats": {
                side: {
                    "form": (t.get("league") or {}).get("form"),
                    "goals_for_avg": ((t.get("league") or {}).get("goals") or {}).get("for", {}).get("average"),
                    "goals_against_avg": ((t.get("league") or {}).get("goals") or {}).get("against", {}).get("average"),
                    "last5": t.get("last_5"),
                }
                for side, t in ((p.get("teams") or {}).items())
            },
            "injuries": [
                {
                    "team": i["team"]["name"],
                    "player": i["player"]["name"],
                    "type": i["player"].get("type"),
                    "reason": i["player"].get("reason"),
                }
                for i in inj
            ],
        }
    dest = ROOT / ".nutmeg-data/jczq/daily/2026-07-04/apifootball-deep.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("WROTE", dest)

    for num, rec in out.items():
        pr = rec["predictions"]
        cmpn = pr.get("comparison") or {}
        print(f"\n== {num} {rec['teams']['home']} vs {rec['teams']['away']} ==")
        print(" advice:", pr.get("advice"), "| percent:", pr.get("percent"), "| u/o:", pr.get("under_over"))
        for k in ("form", "att", "def", "poisson_distribution", "h2h", "goals", "total"):
            if k in cmpn:
                print(f"  cmp {k}: home {cmpn[k].get('home')} away {cmpn[k].get('away')}")
        for side, ts in (rec.get("team_stats") or {}).items():
            l5 = ts.get("last5") or {}
            print(f"  {side}: form={ts.get('form')} GFavg={ts.get('goals_for_avg')} GAavg={ts.get('goals_against_avg')} "
                  f"last5 att={l5.get('att')} def={l5.get('def')} form%={l5.get('form')}")
        if rec["injuries"]:
            print("  injuries:", "; ".join(f"{i['team']}: {i['player']}({i['reason']})" for i in rec["injuries"]))


if __name__ == "__main__":
    main()
