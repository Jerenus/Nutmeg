from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class VAEPModelConfig:
    model_name: str = 'baseline-vaep'
    source: str = 'socceraction'
