#!/usr/bin/env python
"""Deterministic permutation floor for judgment-factor residual effects."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "experiments" / "corpus-v2.json"
DEFAULT_SEED = 20260920
_FACE_CODE = {"home": "3", "draw": "1", "away": "0"}

# 封闭词典（与 nutmeg/decision/legs_audit.py 同源）。
DIRECTIONAL_FLAGS = frozenset(
    {
        "weak_home_draw_trap",
        "league_draw_regime",
        "suspension_breaker_out",
        "self_made_tail",
        "anchor_shield_out",
    }
)
NONDIRECTIONAL_FLAGS = frozenset(
    {
        "two_way_instability",
        "venue_anomaly",
        "dressing_room_turmoil",
        "source_disagreement",
        "undecided_second_leg",
        "information_asymmetry",
    }
)
CRASH_MARKERS = frozenset({"opening_promoted_vs_paper", "opening_new_coach_debut"})
_C11_GAP = (0.05, 0.10)
_C12_DRAW = (0.29, 0.32)
_C8_OFFSET = 0.05


def _slope_pp(xs: list[float], residuals: list[float]) -> float:
    x_mean = sum(xs) / len(xs)
    y_mean = sum(residuals) / len(residuals)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0:
        raise ValueError("factor 至少两个不同取值")
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, residuals, strict=True))
    return 100.0 * numerator / denominator


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def permutation_floor(
    rows: list[dict],
    factor_key: str,
    statistic: str,
    n_perm: int = 1000,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Return the observed residual slope and its shuffled-label null distribution."""
    if statistic != "face_hit_rate_resid_pp":
        raise ValueError(f"不支持的 statistic: {statistic}")
    if n_perm < 1:
        raise ValueError("n_perm 必须 >= 1")
    usable = [
        row
        for row in rows
        if row.get(factor_key) is not None
        and row.get("face_hit") is not None
        and row.get("fair") is not None
    ]
    if len(usable) < 2:
        raise ValueError("可用行不足 2")
    factors = [float(row[factor_key]) for row in usable]
    residuals = [float(row["face_hit"]) - float(row["fair"]) for row in usable]
    observed = _slope_pp(factors, residuals)

    rng = random.Random(seed)
    null: list[float] = []
    shuffled = list(factors)
    for _ in range(n_perm):
        rng.shuffle(shuffled)
        null.append(_slope_pp(shuffled, residuals))
    low = _percentile(null, 0.025)
    high = _percentile(null, 0.975)
    extreme = sum(abs(value) >= abs(observed) for value in null)
    return {
        "n": len(usable),
        "provable_n": sum(row.get("provably_prospective") is True for row in usable),
        "unproven_n": sum(row.get("provably_prospective") is not True for row in usable),
        "observed_pp": round(observed, 6),
        "floor_p2_5": round(low, 6),
        "floor_p97_5": round(high, 6),
        "p_value": round((extreme + 1) / (n_perm + 1), 6),
        "verdict": ("above_floor" if observed < low or observed > high else "indistinguishable"),
        "seed": seed,
        "n_perm": n_perm,
    }


def _load_corpus(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("corpus 必须包含 rows 列表")
    return rows


def _c7_rows(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        labels = row.get("labels") or {}
        precedents = labels.get("precedents") or []
        fair = row.get("fair") or {}
        by_face: dict[str, list[str]] = {}
        for precedent in precedents:
            if isinstance(precedent, list) and len(precedent) >= 2:
                by_face.setdefault(str(precedent[0]), []).append(str(precedent[1]).lower())
        for face, code in _FACE_CODE.items():
            statuses = by_face.get(code)
            if statuses and face in fair:
                output.append(
                    {
                        "factor": int(any(value in {"alive", "live"} for value in statuses)),
                        "face_hit": int(row.get("actual") == code),
                        "fair": fair[face],
                        "provably_prospective": row.get("provably_prospective"),
                    }
                )
    return output


def _anchor_rows(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        labels = row.get("labels") or {}
        integrity = labels.get("anchor_integrity")
        fair = row.get("fair") or {}
        if integrity not in {"pass", "fail"} or not fair:
            continue
        face = max(fair, key=fair.get)
        output.append(
            {
                "factor": int(integrity == "pass"),
                "face_hit": int(row.get("actual") == _FACE_CODE[face]),
                "fair": fair[face],
                "provably_prospective": row.get("provably_prospective"),
            }
        )
    return output


def _death_proof_rows(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        labels = row.get("labels") or {}
        proofs = labels.get("death_three_proofs") or {}
        fair = row.get("fair") or {}
        for face, block in proofs.items():
            raw = (block or {}).get("proof_count")
            if face not in fair or not isinstance(raw, str) or not raw.endswith("/3"):
                continue
            try:
                count = int(raw.split("/", 1)[0])
            except ValueError:
                continue
            output.append(
                {
                    "factor": count,
                    "face_hit": int(row.get("actual") == _FACE_CODE[face]),
                    "fair": fair[face],
                    "provably_prospective": row.get("provably_prospective"),
                }
            )
    return output




def _names(values: object) -> set[str]:
    """Flag names from legs-base lists (str), judgment lists ([name, face]) or plain lists."""
    out: set[str] = set()
    for item in values or []:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
            out.add(item[0])
    return out


def row_flags(row: dict) -> dict[str, set[str]]:
    """Directional / nondirectional / crash flag names on a row, merged across sources
    (legs-base labels, the judgment-file block, research labels), filtered by lexicon."""
    labels = row.get("labels") or {}
    judgment = labels.get("judgment") or {}
    raw = (
        _names(labels.get("directional_flags"))
        | _names(labels.get("nondirectional_flags"))
        | _names(labels.get("crash_markers"))
        | _names(judgment.get("directional_flags"))
        | _names(judgment.get("nondirectional_flags"))
        | _names(judgment.get("crash_markers"))
        | _names(judgment.get("flags"))
    )
    return {
        "directional": raw & DIRECTIONAL_FLAGS,
        "nondirectional": raw & NONDIRECTIONAL_FLAGS,
        "crash": raw & CRASH_MARKERS,
    }


def _has_labels(row: dict) -> bool:
    return bool(row.get("labels"))


def _modal(fair: dict) -> str:
    return max(fair, key=fair.get)


def _flag_rows(rows: list[dict], kind: str, target: str) -> list[dict]:
    """Binary factor = flag kind present; only rows with a label block are admissible,
    otherwise absence of a flag would be indistinguishable from absence of a judgment."""
    output: list[dict] = []
    for row in rows:
        fair = row.get("fair") or {}
        if not _has_labels(row) or len(fair) != 3:
            continue
        flags = row_flags(row)[kind]
        modal = _modal(fair)
        actual = row.get("actual")
        if target == "nonmodal":
            hit, expected = int(actual != _FACE_CODE[modal]), 1.0 - fair[modal]
        elif target == "third":
            third = min(fair, key=fair.get)
            hit, expected = int(actual == _FACE_CODE[third]), fair[third]
        else:
            hit, expected = int(actual == _FACE_CODE[modal]), fair[modal]
        output.append(
            {
                "factor": int(bool(flags)),
                "face_hit": hit,
                "fair": expected,
                "provably_prospective": row.get("provably_prospective"),
            }
        )
    return output


def _directional_flag_rows(rows: list[dict]) -> list[dict]:
    return _flag_rows(rows, "directional", "nonmodal")


def _nondirectional_flag_rows(rows: list[dict]) -> list[dict]:
    return _flag_rows(rows, "nondirectional", "third")


def _crash_marker_rows(rows: list[dict]) -> list[dict]:
    return _flag_rows(rows, "crash", "modal")


def _conf_rows(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        fair = row.get("fair") or {}
        conf = row.get("conf")
        if not isinstance(conf, (int, float)) or len(fair) != 3:
            continue
        modal = _modal(fair)
        output.append(
            {
                "factor": float(conf),
                "face_hit": int(row.get("actual") == _FACE_CODE[modal]),
                "fair": fair[modal],
                "provably_prospective": row.get("provably_prospective"),
            }
        )
    return output


def _price_band_rows(rows: list[dict], band: str) -> list[dict]:
    """Price-only factors admit every priced row (they do not need a judgment)."""
    output: list[dict] = []
    for row in rows:
        fair = row.get("fair") or {}
        if len(fair) != 3:
            continue
        ordered = sorted(fair.values(), reverse=True)
        modal = _modal(fair)
        if band == "c11":
            gap = ordered[0] - ordered[1]
            factor = int(_C11_GAP[0] <= gap < _C11_GAP[1])
            hit, expected = int(row.get("actual") == _FACE_CODE[modal]), fair[modal]
        else:
            draw = fair["draw"]
            factor = int(_C12_DRAW[0] <= draw < _C12_DRAW[1])
            hit, expected = int(row.get("actual") == "1"), draw
        output.append(
            {
                "factor": factor,
                "face_hit": hit,
                "fair": expected,
                "provably_prospective": row.get("provably_prospective"),
            }
        )
    return output


def _false_direction_rows(rows: list[dict]) -> list[dict]:
    return _price_band_rows(rows, "c11")


def _draw_band_rows(rows: list[dict]) -> list[dict]:
    return _price_band_rows(rows, "c12")


def _belief_offset_rows(rows: list[dict]) -> list[dict]:
    """Rows where belief left prior: factor = offset >= 5pp on the belief's modal face;
    outcome = that face opened, expected = its prior (market) probability."""
    output: list[dict] = []
    for row in rows:
        fair = row.get("fair") or {}
        belief = row.get("belief") or {}
        if not row.get("belief_moved") or len(fair) != 3 or len(belief) != 3:
            continue
        face = _modal(belief)
        offset = belief[face] - fair[face]
        output.append(
            {
                "factor": int(offset >= _C8_OFFSET),
                "face_hit": int(row.get("actual") == _FACE_CODE[face]),
                "fair": fair[face],
                "provably_prospective": row.get("provably_prospective"),
            }
        )
    return output


WEAKNESS_TAGS = frozenset(
    {
        "buildup_fragile", "finishing_broken", "high_line_exposed", "late_collapse",
        "low_block_breaker_weak", "makeshift_fullback", "new_cb_pairing", "new_gk",
        "no_natural_striker", "pivot_absent", "rotation_risk", "set_piece_weak",
        "squad_in_flux", "coach_first_games", "dressing_room_noise",
    }
)


def _side_rows(rows: list[dict], pick) -> list[dict]:
    """Team-side factor: for each side with a label block, factor = pick(labels, side)
    (None → skip); outcome = that side won; expected = that side's fair."""
    output: list[dict] = []
    for row in rows:
        labels = row.get("labels") or {}
        fair = row.get("fair") or {}
        if not labels or len(fair) != 3:
            continue
        for side in ("home", "away"):
            value = pick(labels, side)
            if value is None:
                continue
            output.append(
                {
                    "factor": value,
                    "face_hit": int(row.get("actual") == _FACE_CODE[side]),
                    "fair": fair[side],
                    "provably_prospective": row.get("provably_prospective"),
                }
            )
    return output


def _weakness_tag_rows(rows: list[dict]) -> list[dict]:
    """Rows with team_tags on either side; factor = 1 when this side carries any
    weakness tag from the closed lexicon."""
    def pick(labels, side):
        tags = labels.get("team_tags")
        if not isinstance(tags, dict) or not any(tags.get(s) for s in ("home", "away")):
            return None
        return int(bool(set(tags.get(side) or []) & WEAKNESS_TAGS))
    return _side_rows(rows, pick)


def _hole_unpriced_rows(rows: list[dict]) -> list[dict]:
    """Rows with a controlled hole_location; factor = 1 for the side that carries an
    unpriced hole, 0 for the side that carries a priced hole; sides without a hole skip."""
    def pick(labels, side):
        unit, hole_side, priced = (
            labels.get("hole_location_unit"), labels.get("hole_location_side"),
            labels.get("hole_location_priced_in"),
        )
        if unit in (None, "none") or hole_side not in (side, "both") or priced is None:
            return None
        return int(not priced)
    return _side_rows(rows, pick)


def _anchor_side_rows(rows: list[dict]) -> list[dict]:
    """Anchor side only: factor = integrity pass(1)/fail(0); outcome = anchor side won."""
    def pick(labels, side):
        if labels.get("anchor_side") != side:
            return None
        if labels.get("anchor_integrity") not in ("pass", "fail"):
            return None
        return int(labels["anchor_integrity"] == "pass")
    return _side_rows(rows, pick)


_FACTORS = {
    "c7_live_precedent": (
        _c7_rows,
        "face-level alive/live=1, other recorded precedent=0",
    ),
    "anchor_integrity": (
        _anchor_rows,
        "modal face; pass=1, fail=0; symmetric_damage/na excluded",
    ),
    "death_proof_count": (
        _death_proof_rows,
        "face-level proof_count numerator as continuous 0..3",
    ),
    "directional_flag_nonmodal": (
        _directional_flag_rows,
        "labelled rows; directional flag present=1; outcome = non-modal face opened",
    ),
    "nondirectional_flag_third_face": (
        _nondirectional_flag_rows,
        "labelled rows; nondirectional flag present=1; outcome = third face opened",
    ),
    "crash_marker_modal": (
        _crash_marker_rows,
        "labelled rows; crash marker present=1; outcome = modal face opened",
    ),
    "conf_level": (
        _conf_rows,
        "rows with conf; conf as continuous 1..5; outcome = modal face opened",
    ),
    "false_direction_band": (
        _false_direction_rows,
        "all priced rows; gap12 in [5,10)pp = 1; outcome = modal face opened",
    ),
    "draw_underpriced_band": (
        _draw_band_rows,
        "all priced rows; draw fair in [29,32)% = 1; outcome = draw",
    ),
    "belief_offset_anchor": (
        _belief_offset_rows,
        "belief-moved rows; offset >= 5pp on belief modal face = 1; outcome = that face",
    ),
    "weakness_tag_side": (
        _weakness_tag_rows,
        "side-level; any closed-lexicon weakness team_tag on this side = 1; outcome = side won",
    ),
    "hole_unpriced_side": (
        _hole_unpriced_rows,
        "side carrying a controlled hole; unpriced = 1, priced = 0; outcome = side won",
    ),
    "anchor_side_integrity": (
        _anchor_side_rows,
        "anchor side only; integrity pass = 1 / fail = 0; outcome = anchor side won",
    ),
}


_EXTRA_FACTOR_MODULES = ("experiments.rubric_rows",)


def _resolve(factor: str):
    if factor in _FACTORS:
        return _FACTORS[factor]
    import importlib

    for name in _EXTRA_FACTOR_MODULES:
        table = getattr(importlib.import_module(name), "_FACTORS", {})
        if factor in table:
            return table[factor]
    raise KeyError(f"factor {factor!r} not registered in noise_floor or {_EXTRA_FACTOR_MODULES}")


def analyze(
    rows: list[dict],
    *,
    factor: str,
    include_unproven: bool = False,
    n_perm: int = 1000,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Run one factor with the prospective proof gate closed by default.

    因子先找本模块的 `_FACTORS`，找不到再找其他行构造器模块（判断 rubric 的逐项因子在
    `experiments.rubric_rows._FACTORS`，2026-10-02）——闭环 `rsi weights propose --all` 对
    注册表里每个 probability 因子都会调这里。"""
    build_rows, rule = _resolve(factor)
    admitted = (
        rows
        if include_unproven
        else [row for row in rows if row.get("provably_prospective") is True]
    )
    built = build_rows(admitted)
    try:
        result = permutation_floor(
            built, "factor", "face_hit_rate_resid_pp", n_perm=n_perm, seed=seed
        )
    except ValueError as exc:
        # n 不够就是它当前的状态，要看得见（T13 §13.3 ④）
        result = {
            "n": len(built),
            "provable_n": sum(row.get("provably_prospective") is True for row in built),
            "unproven_n": sum(row.get("provably_prospective") is not True for row in built),
            "observed_pp": None,
            "floor_p2_5": None,
            "floor_p97_5": None,
            "p_value": None,
            "verdict": "insufficient",
            "reason": str(exc),
            "seed": seed,
            "n_perm": n_perm,
        }
    return {
        "factor": factor,
        "factor_rule": rule,
        "statistic": "face_hit_rate_resid_pp",
        "sample_mode": "all" if include_unproven else "only-provable",
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factor", required=True, choices=sorted(_FACTORS))
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--n-perm", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--include-unproven",
        action="store_true",
        help="include rows that cannot prove the judgment predates kickoff",
    )
    parser.add_argument(
        "--log", action="store_true", help="append the verdict to experiments/attempts.log"
    )
    args = parser.parse_args()

    result = analyze(
        _load_corpus(args.corpus),
        factor=args.factor,
        include_unproven=args.include_unproven,
        n_perm=args.n_perm,
        seed=args.seed,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.log:
        import sys

        sys.path.insert(0, str(ROOT))
        from experiments.attempts import log_attempt

        log_attempt(
            f"noise_floor {result['factor']}",
            f"mode={result['sample_mode']} n_perm={result['n_perm']} seed={result['seed']}",
            f"n={result['n']} obs={result['observed_pp']}pp "
            f"floor[{result['floor_p2_5']},{result['floor_p97_5']}] p={result['p_value']}",
            result["verdict"],
        )


if __name__ == "__main__":
    main()
