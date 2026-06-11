"""judgment-answers.json 落盘约定(worldcup spec §4.2)。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_judgment_answers import (
    JudgmentAnswers,
    load_judgment_answers,
    validate_answers_payload,
)

VALID = {
    "date": "2026-06-12",
    "answers": [
        {"q_id": "Q_SOFTHOT_周四001", "decision": "keep", "confidence": 4,
         "reason": "欧赔同认"},
    ],
    "agents": ["claude"],
    "final_note": "照引擎执行",
    "answered_at": "2026-06-12T14:30:00+08:00",
}


def test_roundtrip(tmp_path: Path) -> None:
    daily = tmp_path / "2026-06-12"
    daily.mkdir()
    (daily / "judgment-answers.json").write_text(
        json.dumps(VALID, ensure_ascii=False), encoding="utf-8"
    )
    got = load_judgment_answers(daily)
    assert isinstance(got, JudgmentAnswers)
    assert got.answers[0].q_id == "Q_SOFTHOT_周四001"
    assert got.answers[0].confidence == 4


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_judgment_answers(tmp_path) is None


def test_validate_catches_bad_confidence_and_missing_keys() -> None:
    bad = json.loads(json.dumps(VALID))
    bad["answers"][0]["confidence"] = 9
    del bad["final_note"]
    errors = validate_answers_payload(bad)
    assert any("confidence" in e for e in errors)
    assert any("final_note" in e for e in errors)


def test_load_invalid_returns_none(tmp_path: Path) -> None:
    daily = tmp_path / "x"
    daily.mkdir()
    (daily / "judgment-answers.json").write_text("{not json", encoding="utf-8")
    assert load_judgment_answers(daily) is None
