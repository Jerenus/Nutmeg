# scripts/build_wc2026_tournament.py
"""一次性脚本：从 API-Football 拉世界杯 2026 赛程，生成赛制 JSON 骨架。

用法：uv run python scripts/build_wc2026_tournament.py > /tmp/wc2026_skeleton.json
之后人工补 zh 中文名（对照 nutmeg/data/jczq_national_team_aliases.json 反查）、
host 标记（USA/Canada/Mexico）、淘汰赛 home_slot/away_slot（对照 FIFA 官方对阵图）。

数据红线：API 拉不到的字段一律留 FIXME，绝不编造。
"""
from __future__ import annotations

import json
import sys
from datetime import date

from nutmeg.config.settings import get_settings
from nutmeg.data.api_football import ApiFootballClient

WC_LEAGUE_ID = 1
SEASON = 2026
ROUND_TO_STAGE = {
    "Round of 32": "r32",
    "Round of 16": "r16",
    "Quarter-finals": "qf",
    "Semi-finals": "sf",
    "3rd Place Final": "third",
    "Third Place Final": "third",
    "Final": "final",
}


def main() -> None:
    settings = get_settings()
    client = ApiFootballClient(
        base_url=settings.api_football_base_url,
        api_key=settings.api_football_key,
    )
    try:
        batch = client.fetch_upcoming_fixtures(
            league_code="WC2026",
            league_id=WC_LEAGUE_ID,
            season=SEASON,
            date_from=date(2026, 6, 11),
            date_to=date(2026, 7, 19),
        )
    finally:
        client.close()

    matches = []
    for i, fx in enumerate(
        sorted(batch.fixtures, key=lambda f: (f.kickoff_at, f.fixture_id)), 1
    ):
        rnd = fx.round_name or ""
        is_group = rnd.startswith("Group")
        matches.append({
            "match_id": f"M{i:02d}",
            "stage": "group" if is_group else ROUND_TO_STAGE.get(rnd, "FIXME"),
            "group": rnd.split()[1].rstrip(" -123") if is_group else "",
            "date_utc": fx.kickoff_at.date().isoformat(),
            "home": fx.home_team if is_group else "",
            "away": fx.away_team if is_group else "",
            "home_slot": "" if is_group else "FIXME",
            "away_slot": "" if is_group else "FIXME",
            "venue_country": "FIXME",
            "_venue": fx.venue or "",   # 人工核对 venue_country 用，落库前删除
            "_round": rnd,              # 同上
        })
    teams = sorted(
        {(m["home"], m["group"]) for m in matches if m["stage"] == "group"}
        | {(m["away"], m["group"]) for m in matches if m["stage"] == "group"}
    )
    out = {
        "tournament": "FIFA World Cup 2026",
        "window": {"start": "2026-06-11", "end": "2026-07-19"},
        "teams": [
            {"id": name, "zh": "FIXME", "group": grp, "host": False}
            for name, grp in teams
        ],
        "matches": matches,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
