"""calibrate — 聚合 Settlement → FactorVerdict + 词典上限强制(spec §5)。

生死规则(继承 spec §30 反 churn):
- n<30 只积累不判决(keep)。
- n≥30:CLV 命中>0.55 且 brier_delta<0 → keep(转正/维持 active);
        双轴皆平庸(CLV≤0.55 且 brier_delta≥0) → retire;
        一轴好一轴差 → watch。
- ACTIVE_CAP=12:超限强制退休最弱(CLV 最低)。
"""
from __future__ import annotations

from nutmeg.decision.factors import ACTIVE_CAP
from nutmeg.decision.ontology import FactorVerdict

_MIN_SAMPLE = 30
_CLV_BAR = 0.55


def factor_verdict(factor_id: str, settlements: list[dict], *,
                   as_of: str) -> FactorVerdict:
    """settlements: [{brier_delta, clv_hit(0/1)}, ...](已结,非 pending)。"""
    n = len(settlements)
    clv_rate = (sum(s["clv_hit"] for s in settlements) / n) if n else None
    brier_delta = (sum(s["brier_delta"] for s in settlements) / n) if n else None

    if n < _MIN_SAMPLE:
        rec = "keep"                               # 样本不足只积累
    else:
        clv_good = clv_rate > _CLV_BAR
        brier_good = brier_delta < 0
        if clv_good and brier_good:
            rec = "keep"
        elif not clv_good and not brier_good:
            rec = "retire"
        else:
            rec = "watch"
    return FactorVerdict(
        factor_id=factor_id, as_of=as_of, n_reads=n,
        brier_delta_vs_prior=brier_delta, clv_hit_rate=clv_rate,
        direction_hit_rate=None, recommendation=rec, next_review_at="",
    )


def enforce_active_cap(factors, verdicts) -> list[str]:
    """active 因子超 ACTIVE_CAP → 退休最弱(CLV 最低)者,返回被退休的 id 列表。"""
    active = [f for f in factors if f.status == "active"]
    if len(active) <= ACTIVE_CAP:
        return []
    clv_by_id = {v.factor_id: (v.clv_hit_rate or 0.0) for v in verdicts}
    ranked = sorted(active, key=lambda f: clv_by_id.get(f.factor_id, 0.0))
    n_retire = len(active) - ACTIVE_CAP
    return [f.factor_id for f in ranked[:n_retire]]


def run_calibrate(store, *, as_of: str) -> list:
    """聚合所有已结 Settlement → 每因子 FactorVerdict,落库并返回。

    每 Read 的 (brier_delta, clv_hit) 由其 Settlement + prior/belief 得出:
    - clv_hit = 1 if settlement.clv_pp > 0 else 0（clv_pp is None → 该条不计入 CLV）。
    - brier_delta = settlement.brier − brier(prior, outcome);outcome 由 settlement.outcome_90。
      settlement.brier is None(pending)→ 该条不计入。
    """
    from nutmeg.decision.ontology import Read, Settlement
    from nutmeg.decision.scoring import brier

    reads = {r.read_id: r for r in store.load(Read)}
    per_factor: dict[str, list[dict]] = {}
    for st in store.load(Settlement):
        if st.ref_type != "read" or st.brier is None or st.outcome_90 is None:
            continue
        read = reads.get(st.ref_id)
        if read is None or read.shadow or not read.factors:
            continue
        prior_brier = brier(read.prior, st.outcome_90)
        entry = {
            "brier_delta": st.brier - prior_brier,
            "clv_hit": 1 if (st.clv_pp is not None and st.clv_pp > 0) else 0,
        }
        for f in read.factors:
            fid = f.get("factor_id")
            if not fid:
                continue
            per_factor.setdefault(fid, []).append(entry)
            # scope_key 引用 → 追加 factor_id@scope_key 诊断桶(实体层提案 §P3:
            # 证据分辨率,非生死状态机;复合 id 防 store upsert-by-id clobber)
            sk = f.get("scope_key")
            if sk:
                per_factor.setdefault(f"{fid}@{sk}", []).append(entry)

    from dataclasses import replace as _replace
    verdicts = []
    for fid, entries in sorted(per_factor.items()):
        v = factor_verdict(fid, entries, as_of=as_of)
        if "@" in fid:                       # 子判决只做诊断,永不 retire/keep
            v = _replace(v, recommendation="diagnostic")
        verdicts.append(v)
    for v in verdicts:
        store.upsert(v)
    return verdicts


def render_panel(verdicts: list, participation: dict | None = None) -> str:
    """校准面板 markdown——逐因子双轴 + 建议;participation 非 None 时尾部渲染
    参与精度小节(participation_precision 的返回形状,spec §5 判读核心检验)。"""
    lines = [
        "# 决策校准面板", "",
        "| 因子 | n | Brier Δ | CLV 命中 | 建议 |",
        "|---|---|---|---|---|",
    ]
    for v in verdicts:
        bd = "—" if v.brier_delta_vs_prior is None else f"{v.brier_delta_vs_prior:+.3f}"
        clv = "—" if v.clv_hit_rate is None else f"{v.clv_hit_rate:.0%}"
        lines.append(f"| {v.factor_id} | {v.n_reads} | {bd} | {clv} | {v.recommendation} |")
    if participation is not None:
        lines += [
            "", "## 参与精度(divergent vs shadow)", "",
            "| 组 | n | CLV 命中 | avg Brier Δ |",
            "|---|---|---|---|",
        ]
        for group in ("divergent", "shadow"):
            b = participation.get(group) or {}
            clv = ("—" if b.get("clv_hit_rate") is None
                   else f"{b['clv_hit_rate']:.0%}")
            abd = ("—" if b.get("avg_brier_delta") is None
                   else f"{b['avg_brier_delta']:+.3f}")
            lines.append(f"| {group} | {b.get('n', 0)} | {clv} | {abd} |")
    return "\n".join(lines)


def participation_precision(store) -> dict:
    """参与精度(spec §5)——判读的核心检验:divergent Read 是否跑赢 shadow 基线。

    divergent = 非 shadow 且有因子的 Read;baseline = shadow Read。按各自已结
    Settlement 的 CLV 命中率(clv_pp>0)与平均 brier_delta 对比。
    返回 {divergent: {n, clv_hit_rate, avg_brier_delta}, shadow: {n, ...}}。
    无样本的键值为 None。
    """
    from nutmeg.decision.ontology import Read, Settlement
    from nutmeg.decision.scoring import brier

    reads = {r.read_id: r for r in store.load(Read)}
    setts = {s.ref_id: s for s in store.load(Settlement)
             if s.ref_type == "read" and s.brier is not None
             and s.outcome_90 is not None}

    def _bucket(is_divergent: bool) -> dict:
        clv_hits = clv_n = 0
        deltas: list[float] = []
        for rid, read in reads.items():
            divergent = (not read.shadow) and bool(read.factors)
            if divergent != is_divergent:
                continue
            st = setts.get(rid)
            if st is None:
                continue
            deltas.append(st.brier - brier(read.prior, st.outcome_90)
                          if read.prior else 0.0)
            if st.clv_pp is not None:
                clv_n += 1
                clv_hits += 1 if st.clv_pp > 0 else 0
        return {
            "n": len(deltas),
            "clv_hit_rate": (clv_hits / clv_n) if clv_n else None,
            "avg_brier_delta": (sum(deltas) / len(deltas)) if deltas else None,
        }

    return {"divergent": _bucket(True), "shadow": _bucket(False)}


def seed_factors_if_empty(store) -> int:
    """store 无 Factor 时,把种子词典落库(幂等)。返回落库数。"""
    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.ontology import Factor

    if store.load(Factor):
        return 0
    seed = load_seed_factors()
    store.upsert_many(seed)
    return len(seed)


def apply_verdicts(store, verdicts) -> dict:
    """把 FactorVerdict 的判决真正执行成 Factor 状态转换 + 持久化(反积累免疫落地)。

    转换规则(spec §5):recommendation=retire → retired;keep 且 n≥30 且当前 probation
    → active(转正);watch/n<30 → 维持。之后 enforce_active_cap:active 超 12 退休最弱。
    返回 {promoted:[...], retired:[...]}。判断永不在此——只应用 calibrate 已算好的判决。
    """
    from dataclasses import replace

    from nutmeg.decision.calibrate import enforce_active_cap
    from nutmeg.decision.factors import ACTIVE_CAP  # noqa: F401 (供上限语义)
    from nutmeg.decision.ontology import Factor

    seed_factors_if_empty(store)
    factors = {f.factor_id: f for f in store.load(Factor)}
    vmap = {v.factor_id: v for v in verdicts}
    promoted: list[str] = []
    retired: list[str] = []

    for fid, v in vmap.items():
        if "@" in fid or v.recommendation == "diagnostic":
            continue                          # 诊断子判决永不驱动生死(提案复核修正)
        f = factors.get(fid)
        if f is None or f.status == "retired":
            continue
        if v.recommendation == "retire":
            factors[fid] = replace(f, status="retired",
                                   retire_reason=f"双轴平庸(n={v.n_reads})")
            retired.append(fid)
        elif v.recommendation == "keep" and v.n_reads >= 30 and f.status == "probation":
            factors[fid] = replace(f, status="active")
            promoted.append(fid)

    # 词典上限:active 超 12 退休最弱 CLV
    for fid in enforce_active_cap(list(factors.values()), verdicts):
        factors[fid] = replace(factors[fid], status="retired",
                               retire_reason="词典上限(超12退最弱)")
        if fid not in retired:
            retired.append(fid)

    store.upsert_many(list(factors.values()))
    return {"promoted": promoted, "retired": retired}
