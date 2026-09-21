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
}


def analyze(
    rows: list[dict],
    *,
    factor: str,
    include_unproven: bool = False,
    n_perm: int = 1000,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Run one factor with the prospective proof gate closed by default."""
    build_rows, rule = _FACTORS[factor]
    admitted = (
        rows
        if include_unproven
        else [row for row in rows if row.get("provably_prospective") is True]
    )
    result = permutation_floor(
        build_rows(admitted),
        "factor",
        "face_hit_rate_resid_pp",
        n_perm=n_perm,
        seed=seed,
    )
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


if __name__ == "__main__":
    main()
