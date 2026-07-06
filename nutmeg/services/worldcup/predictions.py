"""评判员判定落盘约定(judge spec §1)— agent 写,jczq-report/judge_ledger 读。

容错原则与 jczq_judgment_answers 一致:缺失/损坏 → None + 日志,报告标缺席。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FILENAME = "predictions.json"
JUDGMENTS = ("home", "draw", "away")
_SCORE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
REQUIRED_TOP = ("date", "judge", "picks", "champion_pick", "opinion_ticket",
                "written_at")
REQUIRED_PICK = ("fixture", "judgment", "score", "reason", "confidence")
DEFAULT_STAKE_YUAN = 15


@dataclass(frozen=True, slots=True)
class JudgePick:
    fixture: str
    judgment: str
    score: str
    reason: str
    confidence: int
    upset_flag: bool = False
    baseline_pick: str = ""
    match_id: str = ""
    match_no: str = ""


@dataclass(frozen=True, slots=True)
class OpinionTicket:
    match_no: str
    market: str
    pick: str
    odds: float | None = None
    stake_yuan: int = DEFAULT_STAKE_YUAN
    line: float | None = None      # hhad 让球线(体彩 3 路口径);None=对账时查当日盘面快照


@dataclass(frozen=True, slots=True)
class Predictions:
    date: str
    judge: str
    picks: list[JudgePick]
    champion_pick: dict
    opinion_ticket: OpinionTicket | None
    written_at: str = ""


# 体彩 hhad 是整数让球盘(无 0.5/0.25 半盘),故只认整数;大小写无关(agent 偶写 HHAD)。
_TICKET_MARKET_RE = re.compile(r"^(had|hhad)\s*([+-]\d+)?$", re.IGNORECASE)
_TICKET_PICK_LABELS = {
    "让胜": "home", "受让胜": "home", "主胜": "home", "胜": "home",
    "让平": "draw", "受让平": "draw", "平": "draw",
    "让负": "away", "受让负": "away", "客胜": "away", "负": "away",
}


def _coerce_ticket_market(raw: dict) -> tuple[str, float | None]:
    """容错票面 market:「hhad+2」/「HHAD+2」→ ("hhad", 2.0);显式 line 键优先。"""
    market = str(raw.get("market", "")).strip()
    line = raw.get("line")
    m = _TICKET_MARKET_RE.match(market)
    if m:
        market = m.group(1).lower()
        if line is None and m.group(2) is not None:
            line = float(m.group(2))
    return market, (float(line) if line is not None else None)


def _coerce_ticket_pick(pick: str, market: str) -> str:
    """容错票面 pick:「让平（法国恰净胜2）」→ "draw"。

    未识别的标签**返回原样**而非兜底 code——留给 _grade_ticket_outcome 判 pending
    (人工补结),绝不把无法识别的票当成输(2026-07-06 review:静默记 −stake 是坑)。
    """
    p = re.sub(r"[（(].*?[)）]", "", str(pick)).strip()
    if p in ("home", "draw", "away"):
        return p
    if market in ("had", "hhad"):
        return _TICKET_PICK_LABELS.get(p, pick)
    return pick


def validate_predictions_payload(payload: dict) -> list[str]:
    errors = [f"缺字段 {k}" for k in REQUIRED_TOP if k not in payload]
    for i, p in enumerate(payload.get("picks", [])):
        errors += [f"picks[{i}] 缺字段 {k}" for k in REQUIRED_PICK if k not in p]
        if p.get("judgment") not in JUDGMENTS:
            errors.append(f"picks[{i}] judgment 必须 home/draw/away,得到 {p.get('judgment')!r}")
        conf = p.get("confidence")
        if not (isinstance(conf, int) and 1 <= conf <= 5):
            errors.append(f"picks[{i}] confidence 必须 1-5,得到 {conf!r}")
        if not _SCORE_RE.match(str(p.get("score", ""))):
            errors.append(f"picks[{i}] score 必须 'h-a' 形式,得到 {p.get('score')!r}")
    cp = payload.get("champion_pick")
    if not (isinstance(cp, dict) and cp.get("team")):
        errors.append("champion_pick 必须含 team")
    return errors


def _load_ticket(ticket_raw: dict) -> OpinionTicket:
    market, line = _coerce_ticket_market(ticket_raw)
    return OpinionTicket(
        match_no=ticket_raw["match_no"], market=market,
        pick=_coerce_ticket_pick(ticket_raw["pick"], market),
        odds=ticket_raw.get("odds"),
        stake_yuan=int(ticket_raw.get("stake_yuan", DEFAULT_STAKE_YUAN)),
        line=line,
    )


def load_predictions(daily_dir: Path) -> Predictions | None:
    path = daily_dir / FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        # 历史容错(2026-07-06):agent 偶发把 champion_pick / opinion_ticket 写成
        # 纯字符串;此前会让整天判定作废(误记 absent)。字符串 champion → 包成 dict;
        # 字符串 ticket → 丢弃票面但保留 picks。
        cp_raw = payload.get("champion_pick")
        if isinstance(cp_raw, str) and cp_raw.strip():
            payload = {**payload, "champion_pick": {"team": cp_raw.strip()}}
        if isinstance(payload.get("opinion_ticket"), str):
            logger.warning(
                "opinion_ticket 是字符串,无法结构化对账,按无票处理: %r",
                payload["opinion_ticket"][:80],
            )
            payload = {**payload, "opinion_ticket": None}
        problems = validate_predictions_payload(payload)
        if problems:
            logger.warning("predictions 校验失败: %s", problems)
            return None
        ticket_raw = payload["opinion_ticket"]
        return Predictions(
            date=payload["date"], judge=payload["judge"],
            picks=[
                JudgePick(
                    fixture=p["fixture"], judgment=p["judgment"],
                    score=p["score"], reason=p["reason"],
                    confidence=p["confidence"],
                    upset_flag=bool(p.get("upset_flag", False)),
                    baseline_pick=p.get("baseline_pick", ""),
                    match_id=p.get("match_id", ""),
                    match_no=p.get("match_no", ""),
                )
                for p in payload["picks"]
            ],
            champion_pick=dict(payload["champion_pick"]),
            opinion_ticket=(
                None if ticket_raw is None
                else _load_ticket(ticket_raw)
            ),
            written_at=payload.get("written_at", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("predictions 读取失败", exc_info=True)
        return None
