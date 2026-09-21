"""Mechanical per-match postmortem rows from frozen pre-match artifacts."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nutmeg.decision.legs_audit import exclusion_grade

_FACES = ("3", "1", "0")
_FACE_NAMES = {"3": "home", "1": "draw", "0": "away"}
BJ = ZoneInfo("Asia/Shanghai")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _actual(result: dict) -> str | None:
    home, away = result.get("ft_home"), result.get("ft_away")
    if not isinstance(home, int) or not isinstance(away, int):
        return None
    return "3" if home > away else "0" if away > home else "1"


def _call_kind(faces: str, explicit: object = None) -> str:
    if explicit in {"single", "exclude", "full", "none"}:
        return str(explicit)
    n_faces = len(set(faces) & set(_FACES))
    return {0: "none", 1: "single", 2: "exclude", 3: "full"}[n_faces]


def _proof_count(block: object) -> str | None:
    if not isinstance(block, dict):
        return None
    if block.get("proof_count") is not None:
        return str(block["proof_count"])
    proofs = block.get("proofs") if isinstance(block.get("proofs"), dict) else block
    present = [proofs.get(key) for key in ("a", "b", "c")]
    if not any(value is not None for value in present):
        return None
    return f"{sum(value is True for value in present)}/3"


def _precedent_status(research: dict, leg: dict, face: str) -> str | None:
    named = _FACE_NAMES[face]
    face_status = (leg.get("face_status") or {}).get(named) or {}
    if face_status.get("precedent") is not None:
        return face_status["precedent"]
    for item in research.get("precedents") or leg.get("precedents") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 3 and str(item[0]) == face:
            return item[2]
    return None


def _fair_pp(fair: dict, face: str) -> float | None:
    value = fair.get(_FACE_NAMES[face])
    if not isinstance(value, int | float):
        return None
    return round(float(value) * (1 if value > 1 else 100), 6)


def _prior(
    *,
    actual: str,
    fair: dict,
    research: dict,
    leg: dict,
) -> dict:
    fair_pp = _fair_pp(fair, actual)
    tier = None
    if fair_pp is not None:
        fair_values = {
            face: _fair_pp(fair, face) for face in _FACES
        }
        numeric = {face: value for face, value in fair_values.items() if value is not None}
        modal = max(numeric, key=numeric.get) if numeric else None
        tier = exclusion_grade(fair_pp / 100, is_modal=actual == modal, flat=False)
    named = _FACE_NAMES[actual]
    proof_block = (research.get("death_three_proofs") or {}).get(named)
    if proof_block is None:
        proof_block = (leg.get("face_status") or {}).get(named)
    if proof_block is None:
        proof_block = (leg.get("_d3") or {}).get(named)
    return {
        "fair_pp": fair_pp,
        "exclusion_tier": tier,
        "death_proof_count": _proof_count(proof_block),
        "precedent_status": _precedent_status(research, leg, actual),
    }


def _flags(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item[0] if isinstance(item, (list, tuple)) and item else item) for item in raw]


def _row(
    *,
    match_id: str,
    day: str,
    issue: str | None,
    code: str | None,
    match_no: int | None,
    actual: str,
    call: dict,
    fair: dict,
    research: dict,
    leg: dict,
    source: str,
    computed_at: str,
) -> dict:
    faces = str(call.get("faces") or call.get("face") or "")
    excluded = [face for face in _FACES if face not in faces]
    kind = _call_kind(faces, call.get("kind"))
    hole = research.get("hole_location")
    if not isinstance(hole, dict):
        hole = leg.get("_hole") if isinstance(leg.get("_hole"), dict) else {}
    drift = (research.get("market_snapshot") or {}).get("drift_pp")
    if not isinstance(drift, dict):
        drift = None
    has_call = kind != "none"
    return {
        "match_id": match_id,
        "day": day,
        "issue": issue,
        "code": code,
        "match_no": match_no,
        "actual": actual,
        "call_kind": kind,
        "called_faces": faces or None,
        "hit": actual in faces if has_call else None,
        "excluded_faces": excluded if has_call else [],
        "actual_was_excluded": actual not in faces if has_call else None,
        "actual_face_prior": _prior(
            actual=actual,
            fair=fair,
            research=research,
            leg=leg,
        ),
        "anchor_integrity": research.get("anchor_integrity", leg.get("anchor_integrity")),
        "confidence": research.get("confidence", leg.get("confidence")),
        "directional_flags": _flags(
            research.get("directional_flags", leg.get("directional_flags"))
        ),
        "nondirectional_flags": _flags(
            research.get("nondirectional_flags", leg.get("nondirectional_flags"))
        ),
        "hole_location_unit": hole.get("unit"),
        "drift_pp": drift,
        "source": source,
        "computed_at": computed_at,
    }


def postmortem_candidate_count(*, day: str, issue: str | None, data_dir: Path) -> int:
    if issue:
        calls = _load(data_dir / "zucai" / f"{issue}-calls.json", {})
        if not isinstance(calls, dict):
            return 0
        # 与 postmortem_rows 保持同一口径：`_` 开头是文件级元数据，不是场次
        return sum(1 for key in calls if not str(key).startswith("_"))
    board = _load(data_dir / "jczq" / "daily" / day / "jczq-legs-base.json", {})
    legs = board.get("legs") if isinstance(board, dict) else {}
    return len(legs) if isinstance(legs, dict) else 0


def postmortem_rows(*, day: str, issue: str | None, data_dir: Path) -> list[dict]:
    """Return settled rows only; absent fields remain ``None``."""
    data_dir = Path(data_dir)
    computed_at = datetime.now(BJ).isoformat(timespec="seconds")
    if issue:
        zdir = data_dir / "zucai"
        calls = _load(zdir / f"{issue}-calls.json", {})
        fair_doc = _load(zdir / f"{issue}-fair.json", {})
        legs_doc = _load(zdir / f"{issue}-legs-base.json", {})
        results = _load(zdir / "official-results.json", {}).get(issue)
        outcomes = results.split() if isinstance(results, str) else []
        legs = legs_doc.get("legs") if isinstance(legs_doc, dict) else {}
        rows = []
        # `_` 开头的键是文件级元数据（如 `_meta.built_at` 的时间证据），不是场次
        numbered = {k: v for k, v in calls.items() if not str(k).startswith("_")}
        for raw_no, call in sorted(numbered.items(), key=lambda item: int(item[0])):
            match_no = int(raw_no)
            if match_no > len(outcomes) or outcomes[match_no - 1] not in _FACES:
                continue
            leg = (legs or {}).get(raw_no) or {}
            rows.append(
                _row(
                    match_id=(
                        str(leg["match_id"]) if leg.get("match_id") is not None else None
                    ),
                    day=day,
                    issue=issue,
                    code=None,
                    match_no=match_no,
                    actual=outcomes[match_no - 1],
                    call=call or {},
                    fair=(fair_doc or {}).get(raw_no) or leg.get("fair") or {},
                    research={},
                    leg=leg,
                    source="legs-base",
                    computed_at=computed_at,
                )
            )
        return rows

    day_dir = data_dir / "jczq" / "daily" / day
    board = _load(day_dir / "jczq-legs-base.json", {})
    legs = board.get("legs") if isinstance(board, dict) else {}
    results = _load(data_dir / "jczq" / "jc-results.json", {}).get(day) or {}
    rows = []
    for code, leg in sorted((legs or {}).items()):
        actual = _actual(results.get(code) or {})
        if actual is None:
            continue
        research = _load(day_dir / f"research-{code}.json", {})
        rows.append(
            _row(
                match_id=(
                    str(leg.get("match_id") or (results.get(code) or {}).get("match_id"))
                    if leg.get("match_id") or (results.get(code) or {}).get("match_id")
                    else None
                ),
                day=day,
                issue=None,
                code=code,
                match_no=None,
                actual=actual,
                call={},
                fair=leg.get("fair") or {},
                research=research,
                leg=leg,
                source="research" if research else "legs-base",
                computed_at=computed_at,
            )
        )
    return rows
