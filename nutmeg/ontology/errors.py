"""Typed errors for the v2 ontology kernel."""
from __future__ import annotations


class OntologyError(Exception):
    """Base error for the v2 ontology kernel."""


class MigrationDriftError(OntologyError):
    """A previously applied migration's checksum no longer matches its definition."""


class PermissionDeniedError(OntologyError):
    """An actor role is not permitted to execute an action under a policy version."""


class IdempotencyConflictError(OntologyError):
    """An idempotency key was reused with a different canonical request."""


class OptimisticConcurrencyError(OntologyError):
    """An object changed after the caller read its expected version."""
