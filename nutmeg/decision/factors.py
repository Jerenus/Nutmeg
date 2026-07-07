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


def factor_scopes(factors: list[Factor]) -> dict[str, str]:
    """{factor_id: scope} — read 校验用(team/league scope 引用必带 scope_key)。"""
    return {f.factor_id: f.scope for f in factors}


def sync_factor_scopes(store) -> int:
    """store 的 Factor scope 与种子对齐(幂等,只改 scope,状态/其余字段保留)。

    背景:M2 已落库的行无 scope 字段 → from_dict 默认 match,对 league_bias 等是错的。
    只对齐种子里存在的 factor_id;未来非种子出生的因子不受影响。返回纠偏条数。
    """
    from dataclasses import replace

    seed_scope = {f.factor_id: f.scope for f in load_seed_factors()}
    stored = store.load(Factor)
    changed = 0
    for f in stored:
        want = seed_scope.get(f.factor_id)
        if want and f.scope != want:
            store.upsert(replace(f, scope=want))
            changed += 1
    return changed
