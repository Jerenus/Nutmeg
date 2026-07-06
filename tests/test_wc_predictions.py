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


def test_string_champion_pick_coerced(tmp_path: Path) -> None:
    """2026-07-06 容错:字符串 champion_pick 此前让整日判定作废(误记 absent)。"""
    payload = json.loads(json.dumps(VALID))
    payload["champion_pick"] = "阿根廷(蒙特卡洛22.2%居首)"
    got = load_predictions(_write(tmp_path, payload))
    assert got is not None
    assert got.champion_pick["team"] == "阿根廷(蒙特卡洛22.2%居首)"


def test_string_opinion_ticket_dropped_but_day_survives(tmp_path: Path) -> None:
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = "周日073 南非受让+1 @2.19, 单关¥15"
    got = load_predictions(_write(tmp_path, payload))
    assert got is not None and got.opinion_ticket is None
    assert got.picks[0].judgment == "home"


def test_ticket_market_suffix_and_label_pick_coerced(tmp_path: Path) -> None:
    """「hhad+2」→ market=hhad + line=2;「让平（法国恰净胜2）」→ draw。"""
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = {
        "match_no": "周六090", "market": "hhad+2",
        "pick": "让平（法国恰净胜2）", "odds": 3.5, "stake_yuan": 15,
    }
    got = load_predictions(_write(tmp_path, payload))
    t = got.opinion_ticket
    assert t.market == "hhad" and t.line == 2.0 and t.pick == "draw"


def test_ticket_market_case_insensitive(tmp_path: Path) -> None:
    """2026-07-06 code-review:agent 偶写大写 HHAD,不该退化成 ungradeable。"""
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = {
        "match_no": "周三080", "market": "HHAD-1",
        "pick": "让胜", "odds": 1.64, "stake_yuan": 15,
    }
    got = load_predictions(_write(tmp_path, payload))
    t = got.opinion_ticket
    assert t.market == "hhad" and t.line == -1.0 and t.pick == "home"


def test_ticket_explicit_line_wins_over_market_suffix(tmp_path: Path) -> None:
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = {
        "match_no": "周日073", "market": "hhad", "line": 1,
        "pick": "home", "odds": 2.19, "stake_yuan": 15,
    }
    got = load_predictions(_write(tmp_path, payload))
    assert got.opinion_ticket.line == 1.0
    assert got.opinion_ticket.pick == "home"
