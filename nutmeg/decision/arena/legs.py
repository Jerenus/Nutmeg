"""候选腿：体彩快照 + 国际盘 → 可选的腿。回测与实盘共用，口径只在这里。

胜平负三面用国际 fair 原值；让球只取 ±1，因为主不胜 / 主不败能用 fair 精确相加，其余让球线不出腿。
"""
from __future__ import annotations

from datetime import datetime

from nutmeg.data.prices import devig
from nutmeg.data.sporttery_board import selling_rows
from nutmeg.decision.bj_time import aware
from nutmeg.decision.crowd_source import NATIONAL, TOP5

_FACES = ("home", "draw", "away")
_STANCE_FACE = {"3": "home", "1": "draw", "0": "away"}


def _fair(row: dict | None) -> dict[str, float] | None:
    fair = ((row or {}).get("match_winner") or {}).get("fair_probability")
    if not fair or any(not fair.get(k) for k in _FACES):
        return None
    total = sum(fair[k] for k in _FACES)
    return {k: fair[k] / total for k in _FACES}


def _group(league: str) -> str:
    if league in NATIONAL:
        return "national"
    return "top5" if league in TOP5 else "other"


def _prices(pool: dict | None) -> dict[str, float] | None:
    try:
        return {k: float((pool or {})[k[0]]) for k in _FACES}
    except (KeyError, TypeError, ValueError):
        return None


def _line(pool: dict | None) -> float | None:
    try:
        return float((pool or {}).get("goalLineValue") or (pool or {}).get("goalLine"))
    except (TypeError, ValueError):
        return None


def build_legs(value: dict, odds: dict, day: str, *, ref: datetime,
               stances: dict[str, str] | None = None) -> list[dict]:
    """`day` 在售场的候选腿。`ref` 是取价时点，用来算距开球小时数。`stances`＝{编号: 3/1/0}。"""
    out: list[dict] = []
    for raw, _ in selling_rows(value, day):
        code = raw.get("matchNumStr")
        fair, sp = _fair((odds or {}).get(code)), _prices(raw.get("had"))
        if not code or not fair or not sp:
            continue
        kickoff = aware(f"{raw.get('matchDate')} {raw.get('matchTime')}")
        league = str(raw.get("leagueAbbName") or "")
        base = {
            "code": code, "name": f"{raw.get('homeTeamAbbName')}-{raw.get('awayTeamAbbName')}",
            "league": league, "league_group": _group(league),
            "weekday": datetime.fromisoformat(day).weekday(),
            "kickoff": kickoff.isoformat(),
            "hours_to_kickoff": round((kickoff - ref).total_seconds() / 3600, 3),
            "gap": devig(sp)["home"] - fair["home"],
        }
        fav, dog = max(fair, key=fair.get), min(fair, key=fair.get)
        pick = _STANCE_FACE.get(str((stances or {}).get(code)))
        for face in _FACES:
            out.append(base | {"market": "had", "face": face, "line": None, "sp": sp[face],
                               "p_fair": fair[face], "ret": sp[face] * fair[face],
                               "is_fav": face == fav, "is_dog": face == dog,
                               "stance_match": face == pick})
        hhad, line = _prices(raw.get("hhad")), _line(raw.get("hhad"))
        if hhad and line in (-1.0, 1.0):
            face, price, prob = (("not_win", hhad["away"], fair["draw"] + fair["away"])
                                 if line == -1.0 else
                                 ("not_lose", hhad["home"], fair["home"] + fair["draw"]))
            out.append(base | {"market": "hhad", "face": face, "line": line, "sp": price,
                               "p_fair": prob, "ret": price * prob, "is_fav": False,
                               "is_dog": False, "stance_match": False})
    return out
