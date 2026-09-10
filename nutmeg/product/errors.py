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

    def __init__(self, message: str, *, code: str = "action_blocked") -> None:
        super().__init__(message)
        self.code = code


class ProductNotReadyError(ProductError):
    """The product cannot start against an unhealthy or outdated ontology."""


class ProductTicketError(ProductError):
    """A stable protected-ticket failure exposed by the product boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
