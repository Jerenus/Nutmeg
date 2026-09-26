"""竞彩只放判断腿（Jun 2026-09-27）。

以往按 10/20/50/100 倍赔率档凑腿：合法判断腿不够时就塞进市场最可能的总进球档，
那些腿没有任何判断（09-26 J3 死于 015 总进球 2）。本模块只做确定性算术：
- 腿 = 当天**深研过且未开球**的场次（market-anchor 不进）；
- 玩法 = 胜平负单/双选（概率＝belief）+ 让球单选（由 belief 与体彩总进球形状拟合比分矩阵）；
  不含总进球——我们对进球轴没有结构化判断；
- 排序 = 判断概率 P 降序；不设赔率目标，报每元回报（按各腿判断概率较高面的赔率 ÷ 注数）。
⛔不产生判断，不推荐注金。
"""
from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.dcfit import fit_match

_FACE_KEY = {"3": "home", "1": "draw", "0": "away"}
_HAD_ODDS = {"3": "h", "1": "d", "0": "a"}


def _code(read: dict) -> str:
    return str(read.get("note") or "")[1:].split("|")[0]


def judgment_legs(*, day: str, jczq_dir: Path, now: str) -> list[dict]:
    day_dir = Path(jczq_dir) / "daily" / day
    reads = json.loads((day_dir / "reads.json").read_text(encoding="utf-8"))
    board = json.loads((day_dir / "sporttery_markets.json").read_text(encoding="utf-8"))
    rows = {row["matchNumStr"]: row for group in board.get("matchInfoList") or []
            for row in group.get("subMatchList") or []}
    current = datetime.fromisoformat(now)
    legs: list[dict] = []
    for read in reads:
        code = _code(read)
        row = rows.get(code)
        if read.get("judgment_tier") != "deep_research" or not row or not row.get("had"):
            continue
        kickoff = datetime.fromisoformat(f"{row['matchDate']}T{row['matchTime']}+08:00")
        if kickoff <= current:
            continue
        belief = read["belief"]
        options = []
        for faces in ("3", "1", "0", "31", "30", "10"):
            modal = max(faces, key=lambda f: belief[_FACE_KEY[f]])
            options.append({
                "market": "had", "faces": faces,
                "p": sum(belief[_FACE_KEY[f]] for f in faces),
                "odds": [float(row["had"][_HAD_ODDS[f]]) for f in faces],
                # 双选的回报取判断概率较高那一面的赔率（不取两面里更高的赔率——那是高估）
                "modal_odds": float(row["had"][_HAD_ODDS[modal]]),
            })
        hhad, ttg = row.get("hhad") or {}, row.get("ttg") or {}
        if hhad.get("goalLine") and all(f"s{i}" in ttg for i in range(8)):
            raw = {f"total_{i}": 1 / float(ttg[f"s{i}"]) for i in range(8)}
            total = sum(raw.values())
            cover = fit_match(belief, ttg_fair={k: v / total for k, v in raw.items()},
                              hhad_line=hhad["goalLine"])["hhad_cover"]
            for face, key in (("3", "让胜"), ("1", "让平"), ("0", "让负")):
                options.append({"market": "hhad", "faces": face, "line": hhad["goalLine"],
                                "p": cover[key], "odds": [float(hhad[_HAD_ODDS[face]])],
                                "modal_odds": float(hhad[_HAD_ODDS[face]])})
        legs.append({"code": code, "name": row.get("homeTeamAbbName", "") + "-"
                     + row.get("awayTeamAbbName", ""), "kickoff": kickoff.isoformat(),
                     "belief": belief, "prior": read["prior"], "options": options})
    return legs


def enumerate_combos(legs: list[dict], *, max_legs: int = 4, max_notes: int = 4,
                     top: int = 10) -> list[dict]:
    out: list[dict] = []
    for k in range(2, min(max_legs, len(legs)) + 1):
        for group in itertools.combinations(legs, k):
            for choice in itertools.product(*(leg["options"] for leg in group)):
                notes = 1
                p = 1.0
                odds = 1.0
                for option in choice:
                    notes *= len(option["odds"])
                    p *= option["p"]
                    odds *= option["modal_odds"]
                if notes > max_notes:
                    continue
                out.append({
                    "legs": [{"code": leg["code"], "name": leg["name"], **option}
                             for leg, option in zip(group, choice, strict=True)],
                    "p": p, "notes": notes, "odds": odds, "return_per_yuan": odds / notes,
                })
    out.sort(key=lambda combo: -combo["p"])
    return out[:top]
