"""read 动词的代码侧：摄取 Claude 运行时产出的 Read（校验+落库）+ 自动 shadow。

判断（belief/factor/幅度）由 Claude 产出,本模块只校验 schema + 落库。
无命名因子的在售场由 backfill_shadows 自动补 belief=prior 的影子 Read
（免费攒市场基线校准样本,spec §2/§7 shadow 基线永远在跑）。
"""
from __future__ import annotations

from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.factors import allowed_factor_ids, factor_scopes
from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.read_validate import validate_read


def ingest_reads(payloads: list[dict], *, store, factors: list) -> list[str]:
    """校验并落库 Claude 产出的 Read。返回错误串列表（空=全部落库）。"""
    allowed = allowed_factor_ids(factors)
    scopes = factor_scopes(factors)
    errors: list[str] = []
    for payload in payloads:
        read = Read.from_dict(payload)
        errs = validate_read(read, allowed_factors=allowed, factor_scopes=scopes)
        if errs:
            errors.append(f"{read.read_id}: {'; '.join(errs)}")
            continue
        # 真判读取代同场同市场的市场基线 shadow(顺序无关的去重守卫):
        # 一场一市场只留一条 Read。按 (match_id, market) 去重——had 判读不误删 ttg shadow。
        if not read.shadow:
            for existing in store.load(Read):
                if (existing.match_id == read.match_id and existing.shadow
                        and existing.market == read.market
                        and existing.read_id != read.read_id):
                    store.remove(Read, existing.read_id)
        store.upsert(read)
    return errors


# backfill 覆盖的市场轴:had(方向)+ ttg(进球,2026-07-07 用户定:进球轴判断也要进
# Brier 双轴检验,shadow 起步攒样本)。快照缺该市场 fair(如欧赔源无 ttg)→ 该轴自然跳过。
_SHADOW_MARKETS = ("had", "ttg")


def _shadow_read_id(match_id: str, market: str) -> str:
    # had 保留历史 id 形状(R-shadow-<match>),新增市场轴带市场名后缀区分。
    return f"R-shadow-{match_id}" if market == "had" else f"R-shadow-{market}-{match_id}"


def backfill_shadows(store, *, run_date: str, made_at: str) -> int:
    """对当日有读时快照但无 Read 的 (场, 市场),补 belief=prior 的影子 Read。

    幂等:该 (match_id, market) 已有任何 Read（含 shadow）则跳过。返回新建 shadow 数。
    """
    prefix = f"M-{run_date}-"
    snaps_by_match: dict[str, list] = {}
    for s in store.load(MarketSnapshot):
        if s.match_id.startswith(prefix) and s.kind == "read_time":
            snaps_by_match.setdefault(s.match_id, []).append(s)
    judged = {(r.match_id, r.market) for r in store.load(Read)}
    made = 0
    for match_id, snaps in sorted(snaps_by_match.items()):
        for market in _SHADOW_MARKETS:
            if (match_id, market) in judged:
                continue
            prior, anchor = resolve_prior(snaps, market=market)
            if prior is None:
                continue
            store.upsert(Read(
                read_id=_shadow_read_id(match_id, market), match_id=match_id,
                snapshot_id=anchor.snapshot_id, made_at=made_at, judge="shadow",
                market=market, prior=dict(prior), belief=dict(prior),
                factors=[], confidence=1, shadow=True, note="市场基线影子",
            ))
            made += 1
    return made
