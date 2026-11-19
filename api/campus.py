"""Single integration point: ``install_campus_routes(app)`` adds accounts, enquiries and admin APIs.

Kept separate so ``api/main.py`` (chat, retrieval, uploads) changes by one import and one call.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from api.errors import ServiceError
from api.web_common import require_admin, require_csrf_header

# Applied to existing operational endpoints (re-index / ingestion) that must never be public.
ADMIN_ONLY = [Depends(require_csrf_header), Depends(require_admin)]


def install_campus_routes(app: FastAPI) -> None:
    from api import routes_admin, routes_auth, routes_enquiries

    async def service_error_handler(_: Request, exc: ServiceError):
        return JSONResponse(exc.to_dict(), status_code=exc.status, headers={"Cache-Control": "no-store"})

    app.add_exception_handler(ServiceError, service_error_handler)
    app.include_router(routes_auth.router)
    app.include_router(routes_enquiries.router)
    app.include_router(routes_admin.router)
