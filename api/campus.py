"""Single integration point: ``install_campus_routes(app)`` adds accounts, enquiries and admin APIs.

Kept separate so ``api/main.py`` (chat, retrieval, uploads) changes by one import and one call.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.errors import ServiceError
from api.web_common import require_admin, require_csrf_header

# Applied to existing operational endpoints (re-index / ingestion) that must never be public.
ADMIN_ONLY = [Depends(require_csrf_header), Depends(require_admin)]


def install_campus_routes(app: FastAPI) -> None:
    from api import routes_admin, routes_auth, routes_enquiries

    async def service_error_handler(_: Request, exc: ServiceError):
        return JSONResponse(exc.to_dict(), status_code=exc.status, headers={"Cache-Control": "no-store"})

    async def request_validation_handler(_: Request, exc: RequestValidationError):
        # FastAPI's default validation payload includes rejected input values.
        # Avoid echoing credentials or submitted personal data in error bodies.
        fields = {}
        for error in exc.errors():
            location = error.get("loc", ())
            field = str(location[-1]) if location else "request"
            fields[field] = error.get("msg", "Invalid value.")
        return JSONResponse(
            {"error": {"code": "validation_failed", "message": "Please check the submitted values.", "fields": fields}},
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.include_router(routes_auth.router)
    app.include_router(routes_enquiries.router)
    app.include_router(routes_admin.router)
