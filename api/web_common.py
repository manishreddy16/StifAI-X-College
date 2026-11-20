"""Shared FastAPI pieces for the accounts/enquiries endpoints: cookies, CSRF guard, auth dependencies."""

from __future__ import annotations

import os
import logging

from fastapi import Depends, Request, Response

from api import auth_service, db
from api.auth_service import AuthUser
from api.errors import AuthError, Forbidden

SESSION_COOKIE = "stif_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "stif-campus"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SECURITY_LOG = logging.getLogger("api.security")


def session_hours() -> float:
    try:
        configured = float(os.getenv("STIF_SESSION_HOURS", auth_service.DEFAULT_SESSION_HOURS))
        if not 0.25 <= configured <= 24 * 30:
            raise ValueError
        return configured
    except (ValueError, TypeError):
        return float(auth_service.DEFAULT_SESSION_HOURS)


def client_ip(request: Request) -> str:
    # Behind a reverse proxy this is the proxy address; see HANDOVER.md (rate limits are per process).
    return request.client.host if request.client else "unknown"


def require_csrf_header(request: Request) -> None:
    """State-changing requests must carry a custom header. Browsers cannot send it cross-site
    without a CORS preflight, which this API's CORS policy does not allow."""
    if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        _SECURITY_LOG.warning("Request rejected (reason=csrf_header_missing, method=%s).", request.method)
        raise Forbidden("Request blocked (missing security header).", code="csrf")


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def get_conn():
    with db.session() as conn:
        yield conn


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    flag = (os.getenv("STIF_COOKIE_SECURE") or "auto").strip().lower()
    secure = flag in {"1", "true", "yes"} or (flag == "auto" and request.url.scheme == "https")
    response.set_cookie(SESSION_COOKIE, token, max_age=int(session_hours() * 3600), httponly=True,
                        samesite="lax", secure=secure, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def optional_user(request: Request, conn=Depends(get_conn)) -> AuthUser | None:
    return auth_service.user_for_token(conn, request.cookies.get(SESSION_COOKIE))


def require_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser:
    if user is None:
        raise AuthError("Please sign in to continue.")
    return user


def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if user.role != "admin":
        _SECURITY_LOG.warning("Admin route access denied (reason=role_mismatch).")
        raise Forbidden("You do not have access to this area.")
    return user
