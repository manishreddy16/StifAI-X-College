"""Login, logout, registration and 'who am I' endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from api import auth_service, db
from api.errors import RateLimited
from api.ratelimit import SlidingWindowLimiter
from api.web_common import (SESSION_COOKIE, clear_session_cookie, client_ip, get_conn, no_store, optional_user,
                            require_csrf_header, session_hours, set_session_cookie)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(require_csrf_header), Depends(no_store)])

login_limiter = SlidingWindowLimiter(limit=10, window_seconds=300)
register_limiter = SlidingWindowLimiter(limit=10, window_seconds=3600)


class RegisterBody(BaseModel):
    # Deliberately no "role" field: public sign-up can only ever create students.
    email: str = Field(default="", max_length=400)
    full_name: str = Field(default="", max_length=400)
    password: str = Field(default="", max_length=400)


class LoginBody(BaseModel):
    email: str = Field(default="", max_length=400)
    password: str = Field(default="", max_length=400)


def _start_session(conn, user, request: Request, response: Response) -> dict:
    token, expires = auth_service.create_session(conn, user.id, ttl_hours=session_hours())
    set_session_cookie(response, request, token)
    return {"user": user.public(), "expires_at": expires}


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, conn=Depends(get_conn)):
    if not register_limiter.allow(client_ip(request)):
        raise RateLimited("Too many sign-up attempts. Please try again later.")
    user = auth_service.register_student(conn, email=body.email, full_name=body.full_name, password=body.password)
    return _start_session(conn, user, request, response)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, conn=Depends(get_conn)):
    if not login_limiter.allow(client_ip(request)):
        raise RateLimited("Too many sign-in attempts. Please wait a few minutes and try again.")
    user = auth_service.authenticate(conn, body.email, body.password)
    return _start_session(conn, user, request, response)


@router.post("/logout")
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    auth_service.revoke_token(conn, request.cookies.get(SESSION_COOKIE))
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(optional_user)):
    """200 with user=null when signed out, so the SPA can check quietly on load."""
    return {"user": user.public() if user else None}
