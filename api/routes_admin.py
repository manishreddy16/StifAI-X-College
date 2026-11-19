"""Administrator endpoints. Every route here requires an authenticated user with the admin role."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api import enquiry_service as es
from api.web_common import get_conn, no_store, require_admin, require_csrf_header

router = APIRouter(prefix="/api/v1/admin", tags=["admin"],
                   dependencies=[Depends(require_csrf_header), Depends(no_store), Depends(require_admin)])


class EnquiryUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    admin_notes: str | None = Field(default=None, max_length=20000)


class ProgrammeCreate(BaseModel):
    name: str = Field(default="", max_length=400)


class ProgrammeUpdate(BaseModel):
    is_active: Any = None


@router.get("/stats")
def stats(conn=Depends(get_conn)):
    return es.stats(conn)


@router.get("/enquiries")
def list_enquiries(status: str | None = None, programme_id: int | None = None, q: str | None = Query(default=None, max_length=200),
                   page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=20, ge=1, le=es.MAX_PAGE_SIZE),
                   conn=Depends(get_conn)):
    return es.list_enquiries(conn, status=status or None, programme_id=programme_id, q=q, page=page, page_size=page_size)


@router.get("/enquiries/{enquiry_id}")
def get_enquiry(enquiry_id: int, conn=Depends(get_conn)):
    return {"enquiry": es.get_enquiry(conn, enquiry_id)}


@router.patch("/enquiries/{enquiry_id}")
def update_enquiry(enquiry_id: int, body: EnquiryUpdate, conn=Depends(get_conn)):
    return {"enquiry": es.update_enquiry(conn, enquiry_id, status=body.status, admin_notes=body.admin_notes)}


@router.get("/programmes")
def programmes(conn=Depends(get_conn)):
    return {"items": es.list_programmes(conn, active_only=False)}


@router.post("/programmes", status_code=201)
def add_programme(body: ProgrammeCreate, conn=Depends(get_conn)):
    return {"programme": es.add_programme(conn, body.name)}


@router.patch("/programmes/{programme_id}")
def update_programme(programme_id: int, body: ProgrammeUpdate, conn=Depends(get_conn)):
    if body.is_active not in (True, False):
        from api.errors import ValidationFailed
        raise ValidationFailed({"is_active": "Send true or false."})
    return {"programme": es.set_programme_active(conn, programme_id, body.is_active)}
