from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db, events
from app.config import Settings
from app.logging import configure_logging
from app.middleware import install_request_logging
from app.ratelimit import LOGIN_FAILURE_LIMIT, FailureLimiter
from app.security import (
    client_ip,
    csrf_token,
    install_admin_guard,
    password_matches,
    sign_in_admin,
    sign_out_admin,
    verify_csrf,
)
from app.session import SessionMiddleware
from app.timeutil import format_local_datetime

BASE_DIR = Path(__file__).resolve().parent
logger = configure_logging()

EVENT_FORM_FIELDS = (
    "title",
    "description",
    "location",
    "starts_at",
    "registration_deadline_at",
)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


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
    app.state.login_limiter = FailureLimiter(LOGIN_FAILURE_LIMIT)

    try:
        db.init_db(settings.db_path)
    except Exception:
        # Keep serving so /healthz can report the outage; the container stays up
        # for diagnosis instead of crash-looping.
        logger.exception("database initialization failed")

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.globals["csrf_token"] = csrf_token
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "發生錯誤。"
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status_code": exc.status_code, "message": message},
            status_code=exc.status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_page(request: Request):
        return templates.TemplateResponse(request, "admin_login.html")

    @app.post("/admin/login")
    async def admin_login(request: Request):
        form = await request.form()
        verify_csrf(request, form.get("csrf_token"))

        limiter: FailureLimiter = request.app.state.login_limiter
        ip = client_ip(request)
        if limiter.is_blocked(ip):
            return templates.TemplateResponse(
                request,
                "error.html",
                {"status_code": 429, "message": "請求過於頻繁，請稍後再試。"},
                status_code=429,
            )

        submitted = form.get("password")
        submitted = submitted if isinstance(submitted, str) else ""
        if not password_matches(submitted, settings.admin_password):
            limiter.record_failure(ip)
            return templates.TemplateResponse(
                request,
                "admin_login.html",
                {"error": "密碼錯誤"},
                status_code=401,
            )

        limiter.reset(ip)
        sign_in_admin(request)
        return RedirectResponse("/admin/events", status_code=303)

    @app.post("/admin/logout")
    async def admin_logout(request: Request):
        form = await request.form()
        verify_csrf(request, form.get("csrf_token"))
        sign_out_admin(request)
        return RedirectResponse("/admin/login", status_code=303)

    @app.get("/admin/events", response_class=HTMLResponse)
    def admin_events(request: Request):
        return templates.TemplateResponse(
            request,
            "admin_events.html",
            {
                "events": events.list_events(
                    settings.db_path,
                    base_url=str(request.base_url).rstrip("/"),
                    timezone_name=settings.timezone,
                )
            },
        )

    @app.get("/admin/events/new", response_class=HTMLResponse)
    def admin_event_new_page(request: Request):
        return templates.TemplateResponse(
            request,
            "admin_event_new.html",
            {"values": {}, "errors": {}},
        )

    @app.post("/admin/events/new")
    async def admin_event_create(request: Request):
        form = await request.form()
        verify_csrf(request, _text(form.get("csrf_token")))
        raw = {name: _text(form.get(name)) for name in EVENT_FORM_FIELDS}
        data, errors = events.validate_event_form(raw, settings.timezone)
        if errors:
            return templates.TemplateResponse(
                request,
                "admin_event_new.html",
                {"values": raw, "errors": errors},
                status_code=200,
            )

        events.create_event(settings.db_path, data, app.state.clock())
        return RedirectResponse("/admin/events", status_code=303)

    @app.get("/admin/events/{event_id}", response_class=HTMLResponse)
    def admin_event_detail(request: Request, event_id: int):
        event = events.get_event_detail(
            settings.db_path, event_id, settings.timezone
        )
        if event is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        return templates.TemplateResponse(
            request, "admin_event_detail.html", {"event": event}
        )

    @app.post("/admin/events/{event_id}/rotate-token")
    async def admin_event_rotate_token(request: Request, event_id: int):
        form = await request.form()
        verify_csrf(request, _text(form.get("csrf_token")))
        token = events.rotate_token(settings.db_path, event_id, app.state.clock())
        if token is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        return RedirectResponse("/admin/events", status_code=303)

    @app.get("/e/{token}", response_class=HTMLResponse)
    def public_event(request: Request, token: str):
        event = events.get_event_by_token(settings.db_path, token)
        if event is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        event["status_label"] = events.STATUS_LABELS.get(
            event["status"], event["status"]
        )
        event["starts_label"] = format_local_datetime(
            event["starts_at"], settings.timezone
        )
        event["deadline_label"] = format_local_datetime(
            event["registration_deadline_at"], settings.timezone
        )
        return templates.TemplateResponse(
            request, "event_public.html", {"event": event}
        )

    @app.get("/healthz")
    def healthz():
        try:
            db.ping(settings.db_path)
        except Exception:
            logger.exception("database health check failed")
            return JSONResponse({"status": "error"}, status_code=503)
        return {"status": "ok"}

    # Outer to inner: request logging, session, admin guard, routes.
    install_admin_guard(app)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        always_secure=settings.cookie_secure,
    )
    install_request_logging(app, logger)

    return app
