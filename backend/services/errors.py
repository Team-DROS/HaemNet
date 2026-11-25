"""Domain errors raised by the service layer.

Services state what went wrong in business terms and know nothing about HTTP. The API layer
maps these to responses in one place (see `backend.main`), so rules are never tied to a framework.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class. `status_code` is the HTTP status the API layer answers with."""

    status_code = 400

    def __init__(self, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class BadRequestError(DomainError):
    status_code = 400


class InvalidInputError(DomainError):
    status_code = 422


class UnauthorizedError(DomainError):
    status_code = 401

    def __init__(self, message: str) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class PayloadTooLargeError(DomainError):
    status_code = 413


class UnsupportedMediaError(DomainError):
    status_code = 415


class RateLimitedError(DomainError):
    status_code = 429

    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)} if retry_after else {})


class ServiceUnavailableError(DomainError):
    status_code = 503
