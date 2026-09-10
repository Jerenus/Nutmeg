"""Read-only, business-shaped access to legacy review evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nutmeg.decision.ontology import FactorVerdict
from nutmeg.product.operator_artifacts import ZucaiNightDocument


@dataclass(frozen=True, slots=True)
class ReviewFactorVerdictHistory:
    factor_label: str
    as_of: str
    sample_count: int
    recommendation: str
    brier_delta_vs_prior: str | None
    clv_hit_rate: str | None
    direction_hit_rate: str | None


@dataclass(frozen=True, slots=True)
class ReviewNightCalibrationHistory:
    captured_at: datetime
    source_label: str
    result_count: int
    skipped_count: int


class OperatorReviewHistoryReader:
    """Translate legacy review files without leaking their storage representation."""

    _NIGHT_PATTERN = re.compile(
        r"^(?P<issue>\d{5})-night-\d{4}-\d{2}-\d{2}-af\.json$"
    )

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)

    def factor_verdicts(
        self,
        *,
        factor_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[ReviewFactorVerdictHistory, ...]:
        cutoff = _aware_utc(as_of)
        requested = frozenset(factor_ids)
        if not requested:
            return ()
        path = self._data_dir / "jczq" / "decision" / "verdicts.jsonl"
        if not path.is_file():
            return ()
        latest: dict[str, FactorVerdict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("factor verdict row must be an object")
            verdict = FactorVerdict.from_dict(payload)
            if verdict.factor_id not in requested:
                continue
            if date.fromisoformat(verdict.as_of) > cutoff.date():
                continue
            current = latest.get(verdict.factor_id)
            if current is None or (verdict.as_of, verdict.factor_id) > (
                current.as_of,
                current.factor_id,
            ):
                latest[verdict.factor_id] = verdict
        return tuple(
            ReviewFactorVerdictHistory(
                factor_label=verdict.factor_id,
                as_of=verdict.as_of,
                sample_count=verdict.n_reads,
                recommendation=verdict.recommendation,
                brier_delta_vs_prior=_decimal_text(verdict.brier_delta_vs_prior),
                clv_hit_rate=_decimal_text(verdict.clv_hit_rate),
                direction_hit_rate=_decimal_text(verdict.direction_hit_rate),
            )
            for verdict in sorted(latest.values(), key=lambda item: item.factor_id)
        )

    def night_calibrations(
        self,
        *,
        issue: str,
        as_of: datetime,
    ) -> tuple[ReviewNightCalibrationHistory, ...]:
        if re.fullmatch(r"\d{5}", issue) is None:
            raise ValueError("zucai issue must be five digits")
        cutoff = _aware_utc(as_of)
        root = self._data_dir / "zucai"
        if not root.is_dir():
            return ()
        history = []
        for path in root.iterdir():
            match = self._NIGHT_PATTERN.fullmatch(path.name)
            if not path.is_file() or match is None or match.group("issue") != issue:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("night calibration must be an object")
            skipped = payload.get("skipped")
            if skipped is None:
                skipped = payload.get("pending", [])
            results = payload.get("results")
            if not isinstance(results, dict):
                raise ValueError("night calibration results must be an object")
            document = ZucaiNightDocument.model_validate(
                {
                    "issue": payload.get("issue"),
                    "source": payload.get("source"),
                    "fetched_at": payload.get("fetched_at"),
                    "results": {
                        match_no: {
                            field: result.get(field)
                            for field in ("code", "ft", "home", "away", "status")
                        }
                        for match_no, result in results.items()
                        if isinstance(result, dict)
                    },
                    "skipped": skipped,
                }
            )
            captured_at = _aware_utc(document.fetched_at)
            if document.issue == issue and captured_at <= cutoff:
                history.append(
                    ReviewNightCalibrationHistory(
                        captured_at=captured_at,
                        source_label=document.source,
                        result_count=len(document.results),
                        skipped_count=len(document.skipped),
                    )
                )
        return tuple(sorted(history, key=lambda item: item.captured_at))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("review history cutoff must be timezone-aware")
    return value.astimezone(UTC)


def _decimal_text(value: float | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


__all__ = [
    "OperatorReviewHistoryReader",
    "ReviewFactorVerdictHistory",
    "ReviewNightCalibrationHistory",
]
