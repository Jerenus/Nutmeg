"""评判员记分牌(judge spec §2)— 对账纯函数 + JSONL 读写 + 累计摘要。

幂等:append_day 整日替换(剔除同日旧条目后重写),重跑/补结安全。
评判员的牌子是打出来的:absent 也入账公示。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .predictions import Predictions
from .results import WcResult

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "judge-ledger.jsonl"
# 评判员层上线日(judge spec §2)——此前的日子不存在评判员,不计缺席。
LEDGER_START_DATE = "2026-06-12"


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    n_picks: int
    judgment_rate: float | None
    score_rate: float | None
    baseline_rate: float | None
    upset_precision: float | None   # upset_hit / upset_flag 总数
    ticket_pnl: float
    ticket_n: int
    absent_days: int
    pending: int


GROUP_STAGE_END = "2026-06-27"   # ≤ 此日按小组赛窗口选 pair 首次相遇,之后选最近一次


def _normalize_team(name: str) -> str:
    # 复用别名表同款规约(保留重音/&),避免两处漂移导致 fixture 对不上 → 静默 pending。
    from nutmeg.services.jczq_apifootball_odds import _normalize

    return _normalize(name or "")


def _fixture_pair(fixture: str, aliases: dict[str, str] | None) -> frozenset[str] | None:
    """「阿根廷 vs 佛得角」→ frozenset({argentina, capeverdeislands})(EN normalized)。

    别名缺失 → None(绝不模糊匹配,对齐 jczq_apifootball_odds 惯例)。
    """
    parts = re.split(r"\s+vs\s+|\s+VS\s+", fixture.strip())
    if len(parts) != 2 or not aliases:
        return None
    resolved = []
    for zh in parts:
        en = aliases.get(zh.strip())
        if en is None:
            return None
        resolved.append(_normalize_team(en))
    return frozenset(resolved)


def _result_index(
    results: list[WcResult],
) -> tuple[dict[str, WcResult], dict[frozenset[str], list[WcResult]]]:
    by_id = {r.match_id: r for r in results}
    by_pair: dict[frozenset[str], list[WcResult]] = {}
    for r in results:
        by_pair.setdefault(
            frozenset((_normalize_team(r.home), _normalize_team(r.away))), []
        ).append(r)
    return by_id, by_pair


def _match_result(
    p, pred_date: str,
    by_id: dict[str, WcResult],
    by_pair: dict[frozenset[str], list[WcResult]],
    aliases: dict[str, str] | None,
) -> WcResult | None:
    """match_id 优先;缺失时按 fixture 队名对兜底(2026-07-06:历史 predictions
    从未写 match_id,全部 pending 的根因)。同 pair 双遇(小组+淘汰):小组窗口取
    首次,之后取最近一次。"""
    if p.match_id:
        return by_id.get(p.match_id)
    pair = _fixture_pair(p.fixture, aliases)
    if pair is None:
        return None
    hits = by_pair.get(pair, [])
    if not hits:
        return None
    return hits[0] if pred_date <= GROUP_STAGE_END else hits[-1]


def _grade_ticket_outcome(t, r: WcResult, *, line: float | None) -> str | None:
    """票面口径的 3 路结果:had=胜平负;hhad=90' 净胜球+让球线。

    line=None 且 market=hhad → 无法判(返回 None → pending)。
    AET/PEN 90' 必为平 → margin 0,无需精确比分。
    pick 未能规约成 home/draw/away(标签无法识别)→ None → pending,绝不误判为输。
    """
    if t.pick not in ("home", "draw", "away"):
        return None
    if t.market == "had":
        return r.outcome_90
    if t.market == "hhad":
        if line is None:
            return None
        if r.outcome_90 == "draw":
            margin = 0
        elif r.goals_h_90 is None:
            return None
        else:
            margin = r.goals_h_90 - r.goals_a_90
        adj = margin + line
        return "home" if adj > 0 else "away" if adj < 0 else "draw"
    return None  # 其他玩法暂不自动对账 → pending,人工补结


def reconcile_day(
    pred: Predictions,
    results: list[WcResult],
    *,
    hhad_lines: dict[str, float] | None = None,
    team_aliases: dict[str, str] | None = None,
) -> list[dict]:
    """一天的判定 → ledger 条目(dict,直接可 JSONL)。赛果缺 → pending。"""
    by_id, by_pair = _result_index(results)
    entries: list[dict] = []
    result_by_match_no: dict[str, WcResult | None] = {}
    for p in pred.picks:
        r = _match_result(p, pred.date, by_id, by_pair, team_aliases)
        e: dict = {
            "date": pred.date, "kind": "pick", "judge": pred.judge,
            "match_id": p.match_id, "fixture": p.fixture,
            "judgment": p.judgment, "confidence": p.confidence,
            "upset_flag": p.upset_flag, "pending": r is None,
        }
        if r is not None:
            jh = p.judgment == r.outcome_90
            sh = (
                None if r.goals_h_90 is None
                else p.score == f"{r.goals_h_90}-{r.goals_a_90}"
            )
            e.update({
                "judgment_hit": jh,
                "score_hit": sh,
                "baseline_hit": (
                    p.baseline_pick == r.outcome_90 if p.baseline_pick else None
                ),
                "upset_hit": bool(
                    p.upset_flag and jh and p.judgment != p.baseline_pick
                ),
            })
            if p.match_no:
                result_by_match_no[p.match_no] = r
        elif p.match_no:
            result_by_match_no[p.match_no] = None
        entries.append(e)

    t = pred.opinion_ticket
    if t is not None:
        r = result_by_match_no.get(t.match_no)
        line = t.line
        if line is None and t.market == "hhad" and hhad_lines:
            line = hhad_lines.get(t.match_no)
        outcome = None if r is None else _grade_ticket_outcome(t, r, line=line)
        te: dict = {
            "date": pred.date, "kind": "ticket", "judge": pred.judge,
            "match_no": t.match_no, "market": t.market, "pick": t.pick,
            "odds": t.odds, "stake_yuan": t.stake_yuan,
            "pending": outcome is None,
        }
        if line is not None:
            te["line"] = line
        if outcome is not None:
            te["ticket_outcome"] = outcome
            if t.odds is None:
                te["pnl_yuan"] = None   # 赔率未存,人工补结(spec §5)
            elif t.pick == outcome:
                te["pnl_yuan"] = round(t.stake_yuan * (t.odds - 1.0), 2)
            else:
                te["pnl_yuan"] = float(-t.stake_yuan)
        entries.append(te)
    return entries


def absent_entry(date: str) -> dict:
    return {"date": date, "kind": "absent"}


def load_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("ledger 损坏行已跳过: %r", line[:80])
    return entries


def append_day(path: Path, date: str, entries: list[dict]) -> None:
    """整日替换写入 — 重跑幂等、pending 补结安全。"""
    kept = [e for e in load_ledger(path) if e.get("date") != date]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in kept + entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def ledger_summary(entries: list[dict]) -> LedgerSummary:
    picks = [e for e in entries if e.get("kind") == "pick" and not e.get("pending")]
    tickets = [e for e in entries if e.get("kind") == "ticket" and not e.get("pending")]

    def _rate(key: str) -> float | None:
        vals = [e[key] for e in picks if e.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else None

    flagged = [e for e in picks if e.get("upset_flag")]
    return LedgerSummary(
        n_picks=len(picks),
        judgment_rate=_rate("judgment_hit"),
        score_rate=_rate("score_hit"),
        baseline_rate=_rate("baseline_hit"),
        upset_precision=(
            sum(1 for e in flagged if e.get("upset_hit")) / len(flagged)
            if flagged else None
        ),
        ticket_pnl=sum(e["pnl_yuan"] for e in tickets if e.get("pnl_yuan") is not None),
        ticket_n=len(tickets),
        absent_days=sum(1 for e in entries if e.get("kind") == "absent"),
        pending=sum(1 for e in entries if e.get("pending")),
    )


def _hhad_lines_for_day(daily_dir: Path) -> dict[str, float]:
    """当日 sporttery_markets.json 快照 → {matchNumStr: 让球线}。缺文件/坏结构 → {}。

    票面未显式带 line 时对账用(2026-07-06:hhad 票此前按胜平负口径误评)。
    """
    path = daily_dir / "sporttery_markets.json"
    if not path.exists():
        return {}
    lines: dict[str, float] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for grp in payload.get("matchInfoList") or []:
            for m in grp.get("subMatchList") or []:
                num = m.get("matchNumStr")
                if not num:
                    continue
                for o in m.get("oddsList") or []:
                    if str(o.get("poolCode", "")).upper() != "HHAD":
                        continue
                    raw = o.get("goalLineValue") or o.get("goalLine")
                    if raw not in (None, ""):
                        try:
                            lines[num] = float(raw)
                        except (TypeError, ValueError):
                            pass
    except (json.JSONDecodeError, AttributeError):
        logger.warning("sporttery_markets.json 解析失败: %s", path)
    return lines


def _load_team_aliases() -> dict[str, str]:
    try:
        from nutmeg.services.jczq_apifootball_odds import load_national_team_aliases

        return load_national_team_aliases()
    except Exception:  # noqa: BLE001 — 别名表缺失只降级为 match_id-only 匹配
        logger.warning("国家队别名表加载失败,fixture 兜底匹配停用", exc_info=True)
        return {}


def _reconcile_one(
    output_dir: Path, ledger_path: Path, d: str,
    results, aliases: dict[str, str],
) -> int:
    """单日对账写入;predictions 缺失时记 absent(目录存在才算缺席)。"""
    from .predictions import load_predictions

    daily_dir = output_dir / "daily" / d
    pred = load_predictions(daily_dir)
    if pred is None:
        existing_dates = {e.get("date") for e in load_ledger(ledger_path)}
        if d not in existing_dates and daily_dir.exists():
            append_day(ledger_path, d, [absent_entry(d)])
            return 1
        return 0
    entries = reconcile_day(
        pred, results,
        hhad_lines=_hhad_lines_for_day(daily_dir),
        team_aliases=aliases,
    )
    append_day(ledger_path, d, entries)
    return len(entries)


def reconcile_recent(
    output_dir: Path, *, today: str, days_back: int = 3, sweep_pending: bool = True
) -> int:
    """对账最近 N 天(不含今天)— pending 自动补结;评判员缺席日记 absent。

    2026-07-06 起追加 pending 全量补扫:窗口外仍 pending 的历史日期一并重对账
    (北京凌晨场 08:00 复盘时未终局→此前永久 pending 的根因之二)。

    返回写入的条目数。jczq-report 两条路径(日报/复盘)都调它,幂等。
    """
    from datetime import date, timedelta

    from .results import load_results

    wc_dir = output_dir / "wc2026"
    ledger_path = wc_dir / LEDGER_FILENAME
    results = load_results(wc_dir / "results.json")
    aliases = _load_team_aliases()
    written = 0
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return 0
    recent = {
        (anchor - timedelta(days=back)).isoformat()
        for back in range(1, days_back + 1)
    }
    targets = {d for d in recent if d >= LEDGER_START_DATE}
    if sweep_pending:
        # pending(赛果未到)与 absent(当时无 predictions)都要补扫:后者可能
        # 事后补写了 predictions.json(如 7/05 大冷日晚间补判),窗口外也要救回。
        targets |= {
            e["date"]
            for e in load_ledger(ledger_path)
            if (e.get("pending") or e.get("kind") == "absent")
            and LEDGER_START_DATE <= e.get("date", "") < today
        }
    for d in sorted(targets):
        written += _reconcile_one(output_dir, ledger_path, d, results, aliases)
    return written


def reconcile_range(output_dir: Path, *, since: str, until: str) -> int:
    """[since, until] 闭区间全量重对账(幂等)。维护入口 jczq-judge-reconcile 用:
    修复历史 bug 后重写旧条目(pending 补扫只救 pending,救不了此前误评的票面)。"""
    from datetime import date, timedelta

    from .results import load_results

    wc_dir = output_dir / "wc2026"
    ledger_path = wc_dir / LEDGER_FILENAME
    results = load_results(wc_dir / "results.json")
    aliases = _load_team_aliases()
    try:
        lo, hi = date.fromisoformat(since), date.fromisoformat(until)
    except ValueError:
        return 0
    written = 0
    d = lo
    while d <= hi:
        s = d.isoformat()
        if s >= LEDGER_START_DATE:
            written += _reconcile_one(output_dir, ledger_path, s, results, aliases)
        d += timedelta(days=1)
    return written
