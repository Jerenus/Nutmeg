"""决策本体 v1 的存活对象 — frozen dataclass + to_dict/from_dict + 校验(无 I/O)。

设计: docs/superpowers/specs/2026-07-06-decision-ontology-design.md §2。
2026-10-08 第二轮瘦身:Match/MarketSnapshot/Read/Factor/Settlement/FactorVerdict 随停写的
v1 JSONL 读侧(工作台批准/校准台/账本)退役;判读与结算的事实源在内核。
留下 Team/League(实体画像 `decision-profile`、别名审计、竞赛入库在用)与 Ticket
(只剩 `express.py` 引用,随它一起删)。每对象有 .id(主键,供 DecisionStore 幂等 upsert)。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


def _from_dict(cls, payload: dict):
    """只取 cls 声明的字段(容忍多余键),缺省字段用默认值。"""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in payload.items() if k in known})


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
    # 体彩 leagueAbbName 的口径变体(如 uefa-qualifiers ← 欧冠/欧联/欧协联)。
    # 缺这个字段时 uefa-qualifiers(name_zh="欧战资格赛")对不上任何板面名,
    # 画像整整一个月没挂上过一场比赛(2026-08-05 由 decision-alias-audit 发现)。
    aliases: list[str] = field(default_factory=list)
    profile_notes: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.league_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "League":
        return _from_dict(cls, payload)
