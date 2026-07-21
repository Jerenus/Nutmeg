"""Deterministic filesystem layout for the ontology kernel.

The kernel owns exactly one directory tree under the application ``data_dir``:
its operational SQLite database and its content-addressed artifact store. Paths
are derived, never guessed, and ``ensure_directories`` creates only the two
directories the kernel is responsible for — it never creates the database file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OntologyPaths:
    root: Path
    database: Path
    artifacts: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path | str) -> OntologyPaths:
        root = Path(data_dir) / 'ontology'
        return cls(
            root=root,
            database=root / 'ontology.db',
            artifacts=root / 'artifacts',
        )

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
