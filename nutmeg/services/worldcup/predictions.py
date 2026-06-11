"""评判员判定落盘约定(judge spec §1)— agent 写,jczq-report/judge_ledger 读。

容错原则与 jczq_judgment_answers 一致:缺失/损坏 → None + 日志,报告标缺席。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
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


@dataclass(frozen=True, slots=True)
class Predictions:
    date: str
    judge: str
    picks: list[JudgePick]
    champion_pick: dict
    opinion_ticket: OpinionTicket | None
    written_at: str = ""


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


def load_predictions(daily_dir: Path) -> Predictions | None:
    path = daily_dir / FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
                else OpinionTicket(
                    match_no=ticket_raw["match_no"], market=ticket_raw["market"],
                    pick=ticket_raw["pick"], odds=ticket_raw.get("odds"),
                    stake_yuan=int(ticket_raw.get("stake_yuan", DEFAULT_STAKE_YUAN)),
                )
            ),
            written_at=payload.get("written_at", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("predictions 读取失败", exc_info=True)
        return None
