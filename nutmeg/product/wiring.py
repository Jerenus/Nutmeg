"""Compose the current ontology into headless product services."""
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository


@dataclass(frozen=True, slots=True)
class ProductServices:
    kernel: OntologyKernel
    queries: ProductQueryService
    actions: ProductActionGateway
    settings: AppSettings


def build_product_services(settings: AppSettings) -> ProductServices:
    kernel = build_ontology_kernel(settings)
    status = kernel.status()
    if (
        not status.initialized
        or status.integrity_check != 'ok'
        or status.pending_migrations
    ):
        raise ProductNotReadyError(
            'ontology is not initialized, healthy, and current; run `nutmeg ontology init`'
        )
    repository = ProductReadRepository(kernel.engine)
    return ProductServices(
        kernel=kernel,
        queries=ProductQueryService(repository, kernel),
        actions=ProductActionGateway(kernel, repository),
        settings=settings,
    )
