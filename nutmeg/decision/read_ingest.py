"""read 动词的代码侧：摄取 Claude 运行时产出的 Read（校验+落库）+ 自动 shadow。

判断（belief/factor/幅度）由 Claude 产出,本模块只校验 schema + 落库。
无命名因子的在售场由 backfill_shadows 自动补 belief=prior 的影子 Read
（免费攒市场基线校准样本,spec §2/§7 shadow 基线永远在跑）。
"""
from __future__ import annotations

from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.factors import allowed_factor_ids
from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.read_validate import validate_read


def ingest_reads(payloads: list[dict], *, store, factors: list) -> list[str]:
    """校验并落库 Claude 产出的 Read。返回错误串列表（空=全部落库）。"""
    allowed = allowed_factor_ids(factors)
    errors: list[str] = []
    for payload in payloads:
        read = Read.from_dict(payload)
        errs = validate_read(read, allowed_factors=allowed)
        if errs:
            errors.append(f"{read.read_id}: {'; '.join(errs)}")
            continue
        store.upsert(read)
    return errors


def backfill_shadows(store, *, run_date: str, made_at: str) -> int:
    """对当日有读时快照但无非 shadow Read 的场,补 belief=prior 的影子 Read。

    幂等:已有任何 Read（含 shadow）的 match_id 跳过。返回新建 shadow 数。
    """
    prefix = f"M-{run_date}-"
    snaps_by_match: dict[str, list] = {}
    for s in store.load(MarketSnapshot):
        if s.match_id.startswith(prefix) and s.kind == "read_time":
            snaps_by_match.setdefault(s.match_id, []).append(s)
    judged = {r.match_id for r in store.load(Read)}
    made = 0
    for match_id, snaps in sorted(snaps_by_match.items()):
        if match_id in judged:
            continue
        prior, anchor = resolve_prior(snaps, market="had")
        if prior is None:
            continue
        store.upsert(Read(
            read_id=f"R-shadow-{match_id}", match_id=match_id,
            snapshot_id=anchor.snapshot_id, made_at=made_at, judge="shadow",
            market="had", prior=dict(prior), belief=dict(prior),
            factors=[], confidence=1, shadow=True, note="市场基线影子",
        ))
        made += 1
    return made
