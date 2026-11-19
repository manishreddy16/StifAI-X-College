"""Public enquiry submission, form configuration, and a student's own enquiries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from api import enquiry_service as es
from api.errors import RateLimited
from api.ratelimit import SlidingWindowLimiter
from api.web_common import client_ip, get_conn, no_store, optional_user, require_csrf_header, require_user

router = APIRouter(prefix="/api/v1", tags=["enquiries"], dependencies=[Depends(require_csrf_header), Depends(no_store)])

submit_limiter = SlidingWindowLimiter(limit=10, window_seconds=3600)


class EnquiryBody(BaseModel):
    # Generous caps only bound request size; exact rules and messages live in enquiry_service.
    full_name: str = Field(default="", max_length=400)
    email: str = Field(default="", max_length=400)
    phone: str = Field(default="", max_length=100)
    programme_id: Any = None
    programme_other: str = Field(default="", max_length=400)
    message: str = Field(default="", max_length=10000)
    consent: Any = False


@router.get("/enquiries/form-config")
def form_config(conn=Depends(get_conn)):
    return {
        "programmes": es.list_programmes(conn),
        "consent_text": es.CONSENT_TEXT,
        "consent_version": es.CONSENT_VERSION,
        "limits": {"message_min": es.MESSAGE_MIN, "message_max": es.MESSAGE_MAX},
        "general_label": es.GENERAL_LABEL,
    }


@router.post("/enquiries")
def submit(body: EnquiryBody, request: Request, response: Response, conn=Depends(get_conn),
           user=Depends(optional_user)):
    if not submit_limiter.allow(client_ip(request)):
        raise RateLimited("Too many submissions from this network. Please try again later.")
    result = es.submit_enquiry(conn, body.model_dump(), user=user)
    response.status_code = 200 if result["duplicate"] else 201
    return result


@router.get("/enquiries/mine")
def mine(conn=Depends(get_conn), user=Depends(require_user)):
    return {"items": es.list_for_user(conn, user)}
