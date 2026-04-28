from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class HarnessReport:
    init_script_present: bool
    progress_file_present: bool
    feature_list_present: bool
    total_features: int
    passing_features: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_harness(project_root: Path) -> HarnessReport:
    init_script = project_root / 'init.sh'
    progress_file = project_root / 'agent-progress.md'
    feature_list = project_root / 'feature-list.json'
    total_features = 0
    passing_features = 0
    if feature_list.exists():
        payload = json.loads(feature_list.read_text(encoding='utf-8'))
        total_features = len(payload)
        passing_features = sum(1 for item in payload if item.get('passes'))
    return HarnessReport(
        init_script_present=init_script.exists(),
        progress_file_present=progress_file.exists(),
        feature_list_present=feature_list.exists(),
        total_features=total_features,
        passing_features=passing_features,
    )
