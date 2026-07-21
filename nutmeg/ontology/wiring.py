"""Compose ``AppSettings`` into a ready ontology kernel.

One engine, one artifact store, one Action service and its ``IngestArtifact``
facade — wired but not initialized. Construction is side-effect-light: it never
applies migrations, so ``status`` on a fresh kernel still reports uninitialized.
"""
from __future__ import annotations

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestService
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def build_ontology_kernel(settings: AppSettings) -> OntologyKernel:
    paths = OntologyPaths.from_data_dir(settings.data_dir)
    engine = build_ontology_engine(settings.ontology_db_path)
    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    artifact_store = ContentAddressedArtifactStore(settings.ontology_artifact_dir)
    artifact_ingest = ArtifactIngestService(
        action_service=action_service,
        artifact_store=artifact_store,
    )
    return OntologyKernel(paths=paths, engine=engine, artifact_ingest=artifact_ingest)
