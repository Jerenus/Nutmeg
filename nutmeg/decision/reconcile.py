"""reconcile — Read/Ticket + 赛果 + 收盘快照 → Settlement(双轴)。

演进 judge_ledger 对账纪律。赛果缺 → pending(brier/outcome=None);
收盘快照缺 → clv_pp=None(缺数据绝不伪造,spec §4 多源纪律)。
"""
from __future__ import annotations

from dataclasses import replace

from nutmeg.decision.ontology import Settlement
from nutmeg.decision.scoring import brier, clv_pp


def read_actual(market: str, outcome_90: str | None, score: str | None) -> str | None:
    """Read 的 Brier 靶按市场解析:had→90'胜平负键;ttg→total_{min(总进球,7)}(镜像
    sporttery fair.ttg 桶键);其余市场未支持 → None(不产伪 Brier)。"""
    if market == "had":
        return outcome_90
    if market == "ttg":
        gh, ga = _score_goals(score)
        if gh is None:
            return None
        return f"total_{min(gh + ga, 7)}"
    return None


def settle_read(read, *, outcome_90, score, closing) -> Settlement:
    actual = read_actual(read.market, outcome_90, score)
    b = None if actual is None else brier(read.belief, actual)
    clv = None
    if closing is not None and not read.shadow:
        closing_fair = (closing.fair or {}).get(read.market, {})
        if closing_fair:
            clv = clv_pp(read.belief, read.prior, closing_fair)
    return Settlement(
        settlement_id=f"SET-read-{read.read_id}",
        ref_type="read", ref_id=read.read_id,
        settled_at=read.made_at,          # 占位;编排层用真实结算时刻覆盖
        outcome_90=outcome_90, score=score,
        closing_snapshot_id=(closing.snapshot_id if closing else None),
        brier=b, clv_pp=clv, hit=None, pnl_yuan=None,
    )


def settle_ticket_leg(*, market: str, pick: str, line: float | None,
                      outcome_90: str | None, goals_h: int | None,
                      goals_a: int | None) -> str | None:
    """票面口径 3 路结果(继承 judge_ledger._grade_ticket_outcome 全部 7/06 修复)。

    had=胜平负;hhad=90' 净胜球+让球线。line=None 且 hhad → None(pending)。
    AET/PEN 90'=平 margin 0。pick 无法规约成 home/draw/away → None(pending,不误判输)。
    赛果缺(outcome_90=None)→ None。
    """
    if pick not in ("home", "draw", "away"):
        return None
    if outcome_90 is None:
        return None
    if market == "had":
        return outcome_90
    if market == "hhad":
        if line is None:
            return None
        if outcome_90 == "draw":
            margin = 0
        elif goals_h is None:
            return None
        else:
            margin = goals_h - goals_a
        adj = margin + line
        return "home" if adj > 0 else "away" if adj < 0 else "draw"
    return None


_HAD_OUTCOME = {"胜": "home", "平": "draw", "负": "away"}

# 票面 selection 可读名 → 3 路键(7/07 修:7/06 起 legs 用"让胜·xxx"式 selection,
# 旧口径只认裸键 → 整票被静默跳过永不入账)。had 与 hhad 前缀都规约到同一 3 路键。
_PICK_ALIASES = {
    "home": "home", "draw": "draw", "away": "away",
    "主胜": "home", "胜": "home", "让胜": "home",
    "平": "draw", "让平": "draw",
    "客胜": "away", "负": "away", "让负": "away",
}


def normalize_pick(selection: str | None) -> str | None:
    """"主胜·阿根廷90分钟"/"让负·杰尔+1不败"/"home" → home/draw/away;不可规约 → None。"""
    s = (selection or "").strip()
    if s in _PICK_ALIASES:
        return _PICK_ALIASES[s]
    head = s.replace("・", "·").split("·", 1)[0].strip()
    return _PICK_ALIASES.get(head)


def _score_goals(score: str | None) -> tuple[int | None, int | None]:
    """比分串("2:1"/"2：1")→ (goals_h, goals_a)。缺/坏 → (None, None)。"""
    if not score:
        return None, None
    try:
        gh, ga = (int(x) for x in score.replace("：", ":").split(":"))
    except ValueError:
        return None, None
    return gh, ga


def _result_outcome(result: dict) -> tuple[str | None, str | None, int | None, int | None]:
    """okooo 赛果行 → (outcome_90, score, goals_h, goals_a)。缺 → (None,...)。"""
    had = _HAD_OUTCOME.get(result.get("had", ""))
    score = result.get("score") or None
    gh, ga = _score_goals(score)
    if had is None and gh is not None:
        had = "home" if gh > ga else "away" if gh < ga else "draw"
    return had, score, gh, ga


def settle_tickets(store, *, outcomes: dict, settled_at: str) -> int:
    """Ticket → Settlement(ref_type=ticket, hit + pnl_yuan)。spec §2:结算双账,
    Read 记判断,Ticket 记钱。返回结算票数。确定性金额算术(禁嘴算):

    - single:每票一腿,hit=腿 hit,pnl = hit ? stake×odds−stake : −stake;
    - parlay:全腿 hit 才 hit,pnl = hit ? stake×∏odds−stake : −stake;
    - fushi:M1.5 先跳过(复式拆票结算未实现,不产伪结果)。

    outcomes={canonical match_id: (outcome_90, score)}。任一 leg 无赛果或不可判
    (settle_ticket_leg→None,含 hhad 缺线/pick 不可规约)→ 整票跳过不产 pending
    (继承「未终局跳过」纪律)。幂等:该 ticket 已有 Settlement → 跳过不覆盖。
    """
    from nutmeg.decision.ontology import Ticket

    settled_ids = {s.ref_id for s in store.load(Settlement)
                   if s.ref_type == "ticket"}
    n = 0
    for t in store.load(Ticket):
        if t.ticket_id in settled_ids or t.structure == "fushi":
            continue
        leg_hits: list[bool] | None = []
        for leg in t.legs:
            oc = outcomes.get(str(leg.get("match_id") or ""))
            if oc is None:
                leg_hits = None
                break
            outcome, score = oc
            gh, ga = _score_goals(score)
            raw_line = leg.get("line")
            try:
                line = None if raw_line is None else float(raw_line)
            except (TypeError, ValueError):
                line = None                       # 坏线→hhad 不可判→整票跳过
            pick = normalize_pick(leg.get("selection"))
            res = settle_ticket_leg(
                market=str(leg.get("market") or ""),
                pick=pick or "", line=line,
                outcome_90=outcome, goals_h=gh, goals_a=ga)
            if res is None:
                leg_hits = None
                break
            leg_hits.append(res == pick)
        if not leg_hits:                          # None(不可判)或空 legs 都跳过
            continue
        hit = all(leg_hits)
        if hit:
            combined = 1.0
            for leg in t.legs:
                combined *= float(leg["odds"])
            pnl = round(t.stake_yuan * combined - t.stake_yuan, 2)
        else:
            pnl = -float(t.stake_yuan)
        store.upsert(Settlement(
            settlement_id=f"SET-ticket-{t.ticket_id}", ref_type="ticket",
            ref_id=t.ticket_id, settled_at=settled_at,
            hit=hit, pnl_yuan=pnl))
        n += 1
    return n


def settle_reads_for_matches(store, *, outcomes: dict, settled_at: str) -> int:
    """通用结算:outcomes={match_id: (outcome_90, score)}。对每个**有结果**的 Read 产
    Settlement(Brier+CLV,复用 settle_read + 收盘快照)。canonical 身份→竞彩/zucai 通用。

    只结算 match_id 命中 outcomes 的 Read;无结果的 Read 跳过(不 clobber 其既有/pending
    结算)——canonical 混库(竞彩+zucai 同一 store)下按通道各自喂 outcomes 才安全。
    返回结算的 Read 数。幂等(upsert-by-id)。
    """
    from nutmeg.decision.ontology import MarketSnapshot, Read

    closing_by_match = {
        s.match_id: s for s in store.load(MarketSnapshot) if s.kind == "closing"
    }
    n = 0
    for read in store.load(Read):
        oc = outcomes.get(read.match_id)
        if oc is None:
            continue
        outcome, score = oc
        s = settle_read(read, outcome_90=outcome, score=score,
                        closing=closing_by_match.get(read.match_id))
        s = replace(s, settlement_id=f"SET-read-{read.read_id}",
                    settled_at=settled_at)
        store.upsert(s)
        n += 1
    return n


def settle_day(store, *, run_date: str, results: dict, settled_at: str) -> int:
    """当日竞彩 Read+Ticket → Settlement 落库(spec §2 各一条)。返回结算总数
    (Read 数 + Ticket 数)。

    赛果按 okooo 口径 {竞彩号: {score, had}}。canonical 迁移后 match_id 不含竞彩号,
    改经 Match.channel_refs.jczq_match_no 映射到 canonical,再走通用 settle_reads_for_matches
    (与 zucai 统一;2026-07-06 canonical 修)+ settle_tickets(hit/pnl_yuan)。
    """
    from nutmeg.decision.ontology import Match

    # 竞彩号 → canonical match_id(经 Match.channel_refs)
    no_to_canonical: dict[str, str] = {}
    for m in store.load(Match):
        no = m.channel_refs.get("jczq_match_no")
        if no:
            no_to_canonical[no] = m.match_id
    outcomes: dict = {}
    for no, result in results.items():
        canonical = no_to_canonical.get(no)
        outcome, score, _gh, _ga = _result_outcome(result)
        # 只喂有真实结果的场——未终局(outcome None)不产 pending 结算(诚实计数+不占位)。
        if canonical and outcome is not None:
            outcomes[canonical] = (outcome, score)
    n_reads = settle_reads_for_matches(store, outcomes=outcomes, settled_at=settled_at)
    n_tickets = settle_tickets(store, outcomes=outcomes, settled_at=settled_at)
    return n_reads + n_tickets
