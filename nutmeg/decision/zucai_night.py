"""夜间结果校准（确定性算术层）。

胜负彩 90 分钟口径：AET/PEN 一律取 score.fulltime（26095/26111 场5 口径纪律）。
身份纪律：match_no → fixture_id 必须来自 {issue}-af-map.json 显式映射，
缺失即显式跳过，禁止按队名猜测回退（Intelligence OS 不变量）。
本模块不写 rx、不写 scoreboard——判断与复盘留在主循环。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_FINISHED = {"FT", "AET", "PEN"}


def result_code(ft_home: int, ft_away: int) -> str:
    """90 分钟比分 → 彩果 3/1/0。"""
    if ft_home > ft_away:
        return "3"
    if ft_home == ft_away:
        return "1"
    return "0"


def load_af_map(zucai_dir, issue: str) -> dict[str, int]:
    """{issue}-af-map.json → {match_no(str): fixture_id(int)}。缺文件=空映射（全场显式跳过）。"""
    path = Path(zucai_dir) / f"{issue}-af-map.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8"))
    return {str(k): int(v) for k, v in (data.get("fixtures") or {}).items()}


def fetch_af_day(date: str, *, fetcher=None) -> dict[int, dict]:
    """API-Football /fixtures?date= → {fixture_id: {status, ft_home, ft_away, home, away}}。

    ft_* 取 score.fulltime（90' 口径）；加时/点球比分被刻意丢弃。
    """
    if fetcher is None:
        def fetcher(url, headers):
            import httpx
            resp = httpx.get(url, headers=headers, timeout=25.0)
            resp.raise_for_status()
            return resp.json()
    base = os.environ["NUTMEG_API_FOOTBALL_BASE_URL"].rstrip("/")
    headers = {"x-apisports-key": os.environ["NUTMEG_API_FOOTBALL_KEY"]}
    payload = fetcher(f"{base}/fixtures?date={date}", headers)
    out: dict[int, dict] = {}
    for f in payload.get("response") or []:
        ft = (f.get("score") or {}).get("fulltime") or {}
        out[int(f["fixture"]["id"])] = {
            "status": f["fixture"]["status"]["short"],
            "ft_home": ft.get("home"),
            "ft_away": ft.get("away"),
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
        }
    return out
