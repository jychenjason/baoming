import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.config import Settings
from app.logging import configure_logging
from app.middleware import install_request_logging

BASE_DIR = Path(__file__).resolve().parent
logger = configure_logging()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    math_problem_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    app = FastAPI(title="活動報名")
    app.state.settings = settings
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    app.state.math_problem_factory = math_problem_factory

    try:
        db.init_db(settings.db_path)
    except Exception:
        # Keep serving so /healthz can report the outage; the container stays up
        # for diagnosis instead of crash-looping.
        logger.exception("database initialization failed")

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=24 * 60 * 60,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    install_request_logging(app, logger)

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_page(request: Request):
        return templates.TemplateResponse(request, "admin_login.html")

    @app.get("/healthz")
    def healthz():
        try:
            db.ping(settings.db_path)
        except Exception:
            logger.exception("database health check failed")
            return JSONResponse({"status": "error"}, status_code=503)
        return {"status": "ok"}

    return app
