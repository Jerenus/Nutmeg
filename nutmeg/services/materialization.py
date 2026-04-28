from __future__ import annotations

from dataclasses import dataclass

from nutmeg.data.soccerdata_client import SoccerDataClient
from nutmeg.data.transfermarkt import TransfermarktDataset


@dataclass(slots=True, frozen=True)
class MaterializationResult:
    league_code: str
    season: int
    transfermarkt_rows: int
    soccerdata_rows: int


class MaterializationService:
    def __init__(
        self,
        *,
        transfermarkt_dataset: TransfermarktDataset,
        soccerdata_client: SoccerDataClient,
    ) -> None:
        self._transfermarkt_dataset = transfermarkt_dataset
        self._soccerdata_client = soccerdata_client

    def refresh_snapshot_support_data(self, league_code: str, season: int) -> MaterializationResult:
        return MaterializationResult(
            league_code=league_code,
            season=season,
            transfermarkt_rows=self._transfermarkt_dataset.materialize_local_cache([league_code]),
            soccerdata_rows=self._soccerdata_client.materialize_league_cache(league_code, season),
        )
