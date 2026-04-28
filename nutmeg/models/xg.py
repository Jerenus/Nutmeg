from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class XGModelConfig:
    model_name: str = 'baseline-xg'
    source: str = 'statsbomb-open'
