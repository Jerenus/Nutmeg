"""Ontology kernel repository layer — SQLite schema, migrations, unit of work."""
from __future__ import annotations

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

__all__ = [
    'OntologyUnitOfWork',
    'build_ontology_engine',
]
