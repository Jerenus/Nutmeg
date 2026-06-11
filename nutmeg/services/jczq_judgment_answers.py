"""裁量答案落盘约定(worldcup spec §4.2)— agent 答完 §C 写,jczq-report 读。

容错原则:文件缺失/损坏 → None,报告照出、裁量节标注「裁量未作答」。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FILENAME = "judgment-answers.json"
REQUIRED_TOP = ("date", "answers", "agents", "final_note", "answered_at")
REQUIRED_ANSWER = ("q_id", "decision", "confidence", "reason")


@dataclass(frozen=True, slots=True)
class JudgmentAnswer:
    q_id: str
    decision: str
    confidence: int
    reason: str
    divergent: bool = False


@dataclass(frozen=True, slots=True)
class JudgmentAnswers:
    date: str
    answers: list[JudgmentAnswer]
    agents: list[str] = field(default_factory=list)
    final_note: str = ""
    answered_at: str = ""


def validate_answers_payload(payload: dict) -> list[str]:
    errors = [f"缺字段 {k}" for k in REQUIRED_TOP if k not in payload]
    for i, a in enumerate(payload.get("answers", [])):
        errors += [f"answers[{i}] 缺字段 {k}" for k in REQUIRED_ANSWER if k not in a]
        conf = a.get("confidence")
        if not (isinstance(conf, int) and 1 <= conf <= 5):
            errors.append(f"answers[{i}] confidence 必须 1-5,得到 {conf!r}")
    return errors


def load_judgment_answers(daily_dir: Path) -> JudgmentAnswers | None:
    path = daily_dir / FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if validate_answers_payload(payload):
            logger.warning("judgment-answers 校验失败: %s",
                           validate_answers_payload(payload))
            return None
        return JudgmentAnswers(
            date=payload["date"],
            answers=[
                JudgmentAnswer(
                    q_id=a["q_id"], decision=a["decision"],
                    confidence=a["confidence"], reason=a["reason"],
                    divergent=bool(a.get("divergent", False)),
                )
                for a in payload["answers"]
            ],
            agents=list(payload["agents"]),
            final_note=payload["final_note"],
            answered_at=payload["answered_at"],
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("judgment-answers 读取失败", exc_info=True)
        return None
