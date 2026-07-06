"""Factor 生命周期 + 初始词典种子(spec §5)。

生死机制:出生带 born_from(复盘引用)、初始 probation、n<30 只积累、
双轴达标转 active、双轴平庸退休。ACTIVE_CAP=12 结构性防规则堆积。
"""
from __future__ import annotations

import json
from importlib import resources

from nutmeg.decision.ontology import Factor

ACTIVE_CAP = 12
_SEED_RESOURCE = "decision_factors_seed.json"


def load_seed_factors() -> list[Factor]:
    raw = json.loads(
        resources.files("nutmeg.data").joinpath(_SEED_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return [Factor.from_dict({**f, "status": "probation"}) for f in raw]


def active_factor_ids(factors: list[Factor]) -> set[str]:
    return {f.factor_id for f in factors if f.status == "active"}


def allowed_factor_ids(factors: list[Factor]) -> set[str]:
    """Read 校验用:probation + active 都可引用,retired 拒绝。"""
    return {f.factor_id for f in factors if f.status != "retired"}
