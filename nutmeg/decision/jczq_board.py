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


def build_board_legs(*, day: str, matches: list[dict], jczq_dir: Path) -> dict:
    day_dir = Path(jczq_dir) / "daily" / day
    odds_doc = json.loads((day_dir / "bold_odds.json").read_text(encoding="utf-8"))
    legs: dict[str, dict] = {}
    for match in matches:
        code = match.get("board_code")
        if not code or code not in odds_doc:
            continue
        winner = odds_doc[code].get("match_winner") or {}
        odds = winner.get("odds") or {}
        if not {"home", "draw", "away"} <= set(odds):
            continue
        legs[code] = {
            "match_id": match["match_id"],
            "name": f"{match['home_team']}-{match['away_team']}",
            "home_team": match["home_team"],
            "away_team": match["away_team"],
            "competition": match.get("competition"),
            "kickoff_bj": _to_beijing(match["scheduled_at"]),
            "fair": devig(odds),
            "hhad_line": winner.get("line"),
            "judgment_tier": "price_only",
            "faces": "310",
        }
    doc = {"day": day, "legs": legs}
    (day_dir / "jczq-legs-base.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return doc
