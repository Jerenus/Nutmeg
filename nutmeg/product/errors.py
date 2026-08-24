"""Stable product-layer errors mapped by the HTTP boundary."""
from __future__ import annotations


class ProductError(Exception):
    """Base error for the versioned product boundary."""


class ProductNotFoundError(ProductError):
    """The requested ontology-backed product object does not exist."""
