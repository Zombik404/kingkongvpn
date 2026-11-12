"""Typed application errors, rendered as `{"error": {"code", "message"}}`."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Bad request."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.headers = headers
        self.details = details
        super().__init__(self.message)


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication required."


class InvalidCredentials(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid email or password."


class InvalidToken(AppError):
    status_code = 400
    code = "invalid_token"
    message = "The link or code is invalid or has expired."


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"
    message = "You don't have permission to do this."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflict."


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Try again later."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Temporarily unavailable."
