"""七对象本体 — frozen dataclass + to_dict/from_dict + 校验(无 I/O)。

设计: docs/superpowers/specs/2026-07-06-decision-ontology-design.md §2。
每对象有 .id(主键,供 store 幂等 upsert)与 .to_dict/.from_dict(JSONL 往返)。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


def _from_dict(cls, payload: dict):
    """只取 cls 声明的字段(容忍多余键),缺省字段用默认值。"""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass(frozen=True, slots=True)
class Match:
    match_id: str
    kickoff_at: str
    home: str
    away: str
    competition: str = ""
    channel_refs: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.match_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Match":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    match_id: str
    taken_at: str
    kind: str                  # read_time | closing
    source: str                # sporttery | fcom500 | apifootball | okooo_sp
    fair: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_odds: dict[str, dict[str, float]] = field(default_factory=dict)
    lines: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.snapshot_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "MarketSnapshot":
        return _from_dict(cls, payload)
