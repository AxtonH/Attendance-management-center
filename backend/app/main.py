"""FastAPI app factory.

Keep this file thin: wire routers, configure middleware. Feature logic lives
in app.features.<feature>; shared primitives in app.shared; I/O in app.infra.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.config import get_settings
from app.features.dashboard.route import router as dashboard_router
from app.features.employees.route import router as employees_router
from app.features.exports.route import router as exports_router


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.app_log_level)

    app = FastAPI(
        title="Prezlab Attendance API",
        version="0.1.0",
        description="Read-only attendance data sourced from Supabase (BioTime mirror).",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
        # Expose Content-Disposition so the browser (cross-origin in dev:
        # :3000 → :8000) can read the server-set download filename.
        expose_headers=["Content-Disposition"],
    )

    app.include_router(health.router)
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(employees_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")

    return app


app = create_app()
