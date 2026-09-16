"""Domain errors raised by the graph layer and translated to HTTP responses in ``main.py``."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    key = "error.generic"

    def __init__(self, message: str = "", **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFound(DomainError):
    status_code = 404
    key = "error.not_found"


class Conflict(DomainError):
    status_code = 409
    key = "error.conflict"


class InvalidEdge(DomainError):
    """The (source label, relationship, target label) combination is not allowed."""

    status_code = 422
    key = "error.invalid_edge"


class ValidationFailed(DomainError):
    status_code = 422
    key = "error.validation"
