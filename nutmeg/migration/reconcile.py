"""Reconcile the rebuilt calibrate metrics against the old settlements.

After importing into a fresh kernel, `calibrate` rebuilds `forecast_scores` from the
immutable inputs. The reconciler joins the rebuilt Brier to the old Read-settlement
Brier for the same (match, market) and reports matched / mismatched / coverage with a
per-row delta list. It **asserts nothing about production** — it is evidence for the
go-live decision. A rebuilt score with no old baseline is counted, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.migration.importer import _MARKET_MAP, ImportReport
from nutmeg.storage.duckdb_utils import connect_analytics_db

_TOLERANCE = 1e-6


@dataclass
class ReconciliationReport:
    matched: int = 0
    mismatched: int = 0
    no_baseline: int = 0
    coverage: float = 0.0
    tolerance: float = _TOLERANCE
    method_version: str = 'reconcile-v1'
    deltas: list[float] = field(default_factory=list)


class Reconciler:
    def __init__(self, kernel) -> None:
        self._kernel = kernel

    def reconcile(
        self,
        report: ImportReport,
        reads: list[dict[str, object]],
        settlements: list[dict[str, object]],
        as_of: str,
        built_at: str,
    ) -> ReconciliationReport:
        self._kernel.calibrate.build(CalibrateRequest(as_of=as_of, built_at=built_at))
        scores: dict[tuple[str, str], float] = {}
        with connect_analytics_db(self._kernel._paths.analytics) as connection:
            for match_id, market_id, brier in connection.execute(
                'SELECT match_id, market_definition_id, brier FROM forecast_scores '
                'WHERE brier IS NOT NULL'
            ).fetchall():
                scores[(match_id, market_id)] = float(brier)

        read_key: dict[str, tuple[str, str]] = {}
        for read in reads:
            new_match = report.match_id_map.get(str(read['match_id']))
            market = _MARKET_MAP.get(str(read.get('market')))
            if new_match is not None and market is not None:
                read_key[str(read['read_id'])] = (new_match, market)

        result = ReconciliationReport()
        total = 0
        for settlement in settlements:
            if settlement.get('ref_type') != 'read' or settlement.get('brier') is None:
                continue
            total += 1
            key = read_key.get(str(settlement.get('ref_id')))
            if key is None or key not in scores:
                result.no_baseline += 1
                continue
            delta = abs(scores[key] - float(settlement['brier']))
            result.deltas.append(delta)
            if delta <= _TOLERANCE:
                result.matched += 1
            else:
                result.mismatched += 1
        result.coverage = (result.matched + result.mismatched) / total if total else 0.0
        return result
