"""Build the JCZQ daily board without adding football judgments."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")


def devig(odds: dict[str, float]) -> dict[str, float]:
    raw = {key: 1.0 / float(value) for key, value in odds.items()}
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _to_beijing(iso_value: str) -> str:
    return datetime.fromisoformat(iso_value).astimezone(BJ).isoformat(timespec="seconds")


def build_board_legs(*, day: str, matches: list[dict], jczq_dir: Path,
                     now: datetime | None = None) -> dict:
    """体彩板面 → 当日腿表。当天重跑（17:15 刷新）是**合并**不是覆盖：

    - 已开球的场次原样保留（F9/赛后结算还要用它的赛前腿，不许删、不许改价）；
    - 未开球的已有场次只刷新市场字段，深研写进来的判断字段（tier/stance/faces…）保留；
    - 新场次以 price_only 加入。
    2026-09-26 覆盖式重建把 007–016 冲回 price_only、删掉 001–006。
    """
    day_dir = Path(jczq_dir) / "daily" / day
    odds_doc = json.loads((day_dir / "bold_odds.json").read_text(encoding="utf-8"))
    board_path = day_dir / "jczq-legs-base.json"
    existing = (
        json.loads(board_path.read_text(encoding="utf-8")).get("legs") or {}
        if board_path.exists() else {}
    )
    current = now or datetime.now(BJ)
    legs: dict[str, dict] = {}
    for match in matches:
        code = match.get("board_code")
        if not code or code not in odds_doc:
            continue
        winner = odds_doc[code].get("match_winner") or {}
        odds = winner.get("odds") or {}
        if not {"home", "draw", "away"} <= set(odds):
            continue
        market = {
            "match_id": match["match_id"],
            "name": f"{match['home_team']}-{match['away_team']}",
            "home_team": match["home_team"],
            "away_team": match["away_team"],
            "competition": match.get("competition"),
            "kickoff_bj": _to_beijing(match["scheduled_at"]),
            "fair": devig(odds),
            "hhad_line": winner.get("line"),
        }
        previous = existing.get(code)
        if previous and previous.get("match_id") == match["match_id"]:
            if datetime.fromisoformat(previous["kickoff_bj"]) <= current:
                legs[code] = previous
            else:
                legs[code] = {**previous, **market}
            continue
        legs[code] = {**market, "judgment_tier": "price_only", "faces": "310"}
    for code, previous in existing.items():
        if code not in legs and datetime.fromisoformat(previous["kickoff_bj"]) <= current:
            legs[code] = previous
    legs = dict(sorted(legs.items()))
    doc = {"day": day, "legs": legs}
    board_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc
