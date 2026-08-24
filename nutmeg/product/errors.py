"""Stable product-layer errors mapped by the HTTP boundary."""
from __future__ import annotations


class ProductError(Exception):
    """Base error for the versioned product boundary."""


class ProductNotFoundError(ProductError):
    """The requested ontology-backed product object does not exist."""


class ProductActionNotAllowedError(ProductError):
    """The requested command is outside the explicit product Action whitelist."""


class ProductActionBlockedError(ProductError):
    """Readiness policy blocks the requested state transition."""


class ProductNotReadyError(ProductError):
    """The product cannot start against an unhealthy or outdated ontology."""
