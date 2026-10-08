"""体彩中文队名 → 英文名（API-Football 拼写）的别名表读取（2026-10-08 从已删除的
API-Football 赔率备源模块挪出：身份解析、足彩备料、别名审计与别名提案都读它，与赔率源无关）。"""
from __future__ import annotations

import json
from importlib import resources

_ALIASES_RESOURCE = "jczq_national_team_aliases.json"
_CLUB_ALIASES_RESOURCE = "jczq_club_team_aliases.json"


def _load_flat_aliases(resource: str) -> dict[str, str]:
    """读某张扁平「中文名 → 英文名」别名表（去掉 ``_`` 注释键）。"""
    raw = json.loads(
        resources.files("nutmeg.data").joinpath(resource).read_text(encoding="utf-8")
    )
    return {
        key: str(value)
        for key, value in raw.items()
        if not key.startswith("_") and isinstance(value, str)
    }


def load_national_team_aliases() -> dict[str, str]:
    """国家队中文名 → 英文名。"""
    return _load_flat_aliases(_ALIASES_RESOURCE)


def load_club_team_aliases() -> dict[str, str]:
    """俱乐部中文名 → 英文名（欧战与各国联赛）。"""
    return _load_flat_aliases(_CLUB_ALIASES_RESOURCE)


def load_team_aliases() -> dict[str, str]:
    """国家队 + 俱乐部合并；两表键域天然不相交，偶有同名以俱乐部表为准。"""
    return {**load_national_team_aliases(), **load_club_team_aliases()}
