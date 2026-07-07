"""九对象（2026-07-07 实体层增补 Team/League）本体
— frozen dataclass + to_dict/from_dict + 校验(无 I/O)。

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
    home_team_id: str | None = None      # 策展 resolve 命中才填;未命中 None 绝不伪造
    away_team_id: str | None = None
    competition_id: str | None = None

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


@dataclass(frozen=True, slots=True)
class Read:
    read_id: str
    match_id: str
    snapshot_id: str
    made_at: str
    judge: str
    market: str
    prior: dict[str, float]
    belief: dict[str, float]
    factors: list[dict] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)
    falsifier: str = ""
    confidence: int = 3
    shadow: bool = False
    note: str = ""

    @property
    def id(self) -> str:
        return self.read_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Read":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Factor:
    factor_id: str
    name_zh: str
    definition: str
    born_at: str
    born_from: str
    status: str = "probation"           # probation | active | retired
    retire_reason: str = ""
    scope: str = "match"                # match|pairing|appearance|team|league(提案§P2 因子海拔)

    @property
    def id(self) -> str:
        return self.factor_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Factor":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_id: str
    channel: str                        # jczq | shengfucai | renjiu
    made_at: str
    legs: list[dict]
    structure: str                      # single | parlay | fushi
    stake_yuan: int
    computed_hit_prob: float | None = None
    tag: str = ""
    budget_bucket: str = ""

    @property
    def id(self) -> str:
        return self.ticket_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Ticket":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Settlement:
    settlement_id: str
    ref_type: str                       # read | ticket
    ref_id: str
    settled_at: str
    outcome_90: str | None = None
    score: str | None = None
    closing_snapshot_id: str | None = None
    brier: float | None = None
    clv_pp: float | None = None
    hit: bool | None = None
    pnl_yuan: float | None = None

    @property
    def id(self) -> str:
        return self.settlement_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Settlement":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class FactorVerdict:
    factor_id: str
    as_of: str
    n_reads: int
    brier_delta_vs_prior: float | None
    clv_hit_rate: float | None
    direction_hit_rate: float | None
    recommendation: str                 # keep | watch | retire
    next_review_at: str = ""

    @property
    def id(self) -> str:
        return self.factor_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "FactorVerdict":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Team:
    """持久实体节点——信念输入与跨场学习的沉淀处(实体层提案 §P2)。
    只为"我们对它有知识"的实体而生:策展式创建,绝不由 sense 自动造。"""
    team_id: str
    name_zh: str = ""
    name_en: str = ""
    aliases: list[str] = field(default_factory=list)
    competition_ids: list[str] = field(default_factory=list)
    profile_notes: list[dict] = field(default_factory=list)  # {key,note,evidence,at}

    @property
    def id(self) -> str:
        return self.team_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Team":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class League:
    """持久实体节点——联赛级结构偏差(league scope 因子)的沉淀处。"""
    league_id: str
    name_zh: str = ""
    name_en: str = ""
    country: str = ""
    season: str = ""
    profile_notes: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.league_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "League":
        return _from_dict(cls, payload)
