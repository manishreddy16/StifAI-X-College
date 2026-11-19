"""Framework-independent service errors. Routes translate these into HTTP responses."""

from __future__ import annotations


class ServiceError(Exception):
    status = 400
    code = "error"

    def __init__(self, message: str, *, fields: dict[str, str] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}
        if code:
            self.code = code

    def to_dict(self) -> dict:
        body = {"code": self.code, "message": self.message}
        if self.fields:
            body["fields"] = self.fields
        return {"error": body}


class ValidationFailed(ServiceError):
    status = 422
    code = "validation_failed"

    def __init__(self, fields: dict[str, str], message: str = "Please correct the highlighted fields."):
        super().__init__(message, fields=fields)


class AuthError(ServiceError):
    status = 401
    code = "unauthenticated"


class AccountLocked(ServiceError):
    status = 429
    code = "account_locked"


class Forbidden(ServiceError):
    status = 403
    code = "forbidden"


class NotFound(ServiceError):
    status = 404
    code = "not_found"


class Conflict(ServiceError):
    status = 409
    code = "conflict"


class RateLimited(ServiceError):
    status = 429
    code = "rate_limited"
