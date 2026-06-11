"""predictions.json 落盘约定(judge spec §1)。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.worldcup.predictions import (
    Predictions,
    load_predictions,
    validate_predictions_payload,
)

VALID = {
    "date": "2026-06-12",
    "judge": "claude",
    "picks": [
        {"fixture": "墨西哥 vs 南非", "match_id": "M01", "match_no": "周四001",
         "judgment": "home", "score": "2-1", "reason": "主场+对手中场弱",
         "confidence": 4, "upset_flag": False, "baseline_pick": "home"},
    ],
    "champion_pick": {"team": "Argentina", "reason": "板凳深度+淘汰赛基因"},
    "opinion_ticket": {"match_no": "周四001", "market": "had", "pick": "home",
                       "odds": 1.85, "stake_yuan": 15},
    "written_at": "2026-06-12T14:30:00+08:00",
}


def _write(tmp_path: Path, payload: dict) -> Path:
    daily = tmp_path / "2026-06-12"
    daily.mkdir(exist_ok=True)
    (daily / "predictions.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return daily


def test_roundtrip(tmp_path: Path) -> None:
    got = load_predictions(_write(tmp_path, VALID))
    assert isinstance(got, Predictions)
    assert got.picks[0].judgment == "home"
    assert got.picks[0].confidence == 4
    assert got.opinion_ticket.stake_yuan == 15
    assert got.champion_pick["team"] == "Argentina"


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_predictions(tmp_path) is None


def test_null_ticket_is_legal(tmp_path: Path) -> None:
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = None
    got = load_predictions(_write(tmp_path, payload))
    assert got is not None and got.opinion_ticket is None


def test_validate_catches_bad_judgment_confidence_score() -> None:
    bad = json.loads(json.dumps(VALID))
    bad["picks"][0]["judgment"] = "win"
    bad["picks"][0]["confidence"] = 0
    bad["picks"][0]["score"] = "2:1"
    errors = validate_predictions_payload(bad)
    assert any("judgment" in e for e in errors)
    assert any("confidence" in e for e in errors)
    assert any("score" in e for e in errors)


def test_corrupt_returns_none(tmp_path: Path) -> None:
    daily = tmp_path / "x"
    daily.mkdir()
    (daily / "predictions.json").write_text("{broken", encoding="utf-8")
    assert load_predictions(daily) is None
