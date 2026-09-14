"""国际欧赔共识的书目口径配置（``config/odds_books.yaml``）。

书目集合直接决定去水 fair，是判断层的输入口径；改它属判据变更，应当能被审计、被
diff、被复盘引用——写死在代码里做不到这些，故单独成文件。

配置缺失/损坏时**不静默退化**：抛 ``OddsBooksConfigError``。用一套沉默的内置默认
值顶替一份读不到的口径文件，等于让判断层拿着一个谁也没审过的书目集合继续跑。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = [
    "OddsBooksConfig",
    "OddsBooksConfigError",
    "load_odds_books_config",
]

_DEFAULT_PATH = "config/odds_books.yaml"


class OddsBooksConfigError(RuntimeError):
    """书目口径配置缺失或不可解析。"""


@dataclass(frozen=True, slots=True)
class OddsBooksConfig:
    excluded_ids: frozenset[str]
    sharp_ids: frozenset[str]
    names_by_id: dict[str, str]
    min_consensus_books: int
    kickoff_tolerance: timedelta
    min_euro_books: int


def _ids(rows, where: str) -> tuple[frozenset[str], dict[str, str]]:
    out: dict[str, str] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            raise OddsBooksConfigError(f"{where} 里有缺 id 的条目：{row!r}")
        out[str(row["id"]).strip()] = str(row.get("name") or "").strip()
    if not out:
        raise OddsBooksConfigError(f"{where} 为空——拒绝用空书目集合跑共识")
    return frozenset(out), out


@lru_cache(maxsize=1)
def load_odds_books_config(config_path: str = _DEFAULT_PATH) -> OddsBooksConfig:
    path = Path(config_path)
    if not path.exists():
        raise OddsBooksConfigError(f"书目口径配置不存在：{path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise OddsBooksConfigError(f"书目口径配置无法解析：{path}: {exc}") from exc

    section = payload.get("titan007") or {}
    excluded_ids, excluded_names = _ids(section.get("excluded"), "titan007.excluded")
    sharp_ids, sharp_names = _ids(section.get("sharp"), "titan007.sharp")

    overlap = excluded_ids & sharp_ids
    if overlap:
        raise OddsBooksConfigError(
            f"同一家既在 excluded 又在 sharp：{sorted(overlap)}——口径自相矛盾"
        )

    thresholds = section.get("thresholds") or {}
    try:
        min_consensus = int(thresholds["min_consensus_books"])
        tolerance = int(thresholds["kickoff_tolerance_minutes"])
        min_euro = int(thresholds["min_euro_books"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OddsBooksConfigError(
            f"titan007.thresholds 缺项或非整数：{thresholds!r}"
        ) from exc
    if min_consensus < 1 or tolerance < 0 or min_euro < 1:
        raise OddsBooksConfigError(f"titan007.thresholds 取值非法：{thresholds!r}")

    return OddsBooksConfig(
        excluded_ids=excluded_ids,
        sharp_ids=sharp_ids,
        names_by_id={**excluded_names, **sharp_names},
        min_consensus_books=min_consensus,
        kickoff_tolerance=timedelta(minutes=tolerance),
        min_euro_books=min_euro,
    )
