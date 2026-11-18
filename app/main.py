import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
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
    csrf_protected_form,
    csrf_token,
    install_admin_guard,
    password_matches,
    sign_in_admin,
    sign_out_admin,
)
from app.session import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
logger = configure_logging()

MATH_GATE_LIMIT = 20
MATH_GATE_SESSION_PREFIX = "math_gate:"

def _form_text(value) -> str:
    return value if isinstance(value, str) else ""


def _new_math_problem() -> tuple[int, int]:
    left = secrets.randbelow(90) + 10
    right = secrets.randbelow(min(9, 100 - left)) + 1
    return left, right


def _math_problem(request: Request) -> tuple[int, int]:
    factory = request.app.state.math_problem_factory or _new_math_problem
    problem = factory()
    if (
        not isinstance(problem, (tuple, list))
        or len(problem) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) for value in problem)
    ):
        raise ValueError("math_problem_factory must return a pair of integers")
    left, right = problem
    if not 10 <= left <= 99 or not 1 <= right <= 9 or left + right > 100:
        raise ValueError("math_problem_factory returned a problem outside the allowed range")
    return left, right


def _math_gate_key(token: str) -> str:
    return f"{MATH_GATE_SESSION_PREFIX}{token}"


def _math_gate_passed(request: Request, token: str) -> bool:
    raw = request.session.get(_math_gate_key(token))
    if not isinstance(raw, str):
        return False
    try:
        verified_at = datetime.fromisoformat(raw)
    except ValueError:
        request.session.pop(_math_gate_key(token), None)
        return False
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    now = request.app.state.clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now - verified_at >= timedelta(hours=24) or now < verified_at:
        request.session.pop(_math_gate_key(token), None)
        return False
    return True


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
    app.state.math_gate_limiter = FailureLimiter(MATH_GATE_LIMIT)

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
        form = await csrf_protected_form(request)

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
        await csrf_protected_form(request)
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
        form = await csrf_protected_form(request)
        raw = {name: _form_text(form.get(name)) for name in events.FORM_FIELDS}
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
        await csrf_protected_form(request)
        token = events.rotate_token(settings.db_path, event_id, app.state.clock())
        if token is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        return RedirectResponse("/admin/events", status_code=303)

    @app.get("/e/{token}", response_class=HTMLResponse)
    def public_event(request: Request, token: str):
        event = events.get_event_by_token(settings.db_path, token)
        if event is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        if not _math_gate_passed(request, token):
            challenge_key = _math_gate_key(token) + ":challenge"
            problem = request.session.get(challenge_key)
            if not isinstance(problem, dict) or not all(
                isinstance(problem.get(key), int) for key in ("left", "right", "answer")
            ):
                left, right = _math_problem(request)
                problem = {"left": left, "right": right, "answer": left + right}
                request.session[challenge_key] = problem
            return templates.TemplateResponse(
                request,
                "event_math_gate.html",
                {
                    "event": events.present_event(event, settings.timezone),
                    "left": problem["left"],
                    "right": problem["right"],
                    "error": None,
                },
            )
        return templates.TemplateResponse(
            request,
            "event_public.html",
            {"event": events.present_event(event, settings.timezone)},
        )

    @app.post("/e/{token}/verify", response_class=HTMLResponse)
    async def public_event_verify(request: Request, token: str):
        event = events.get_event_by_token(settings.db_path, token)
        if event is None:
            raise HTTPException(status_code=404, detail="找不到活動。")
        if _math_gate_passed(request, token):
            return RedirectResponse(f"/e/{token}", status_code=303)

        form = await csrf_protected_form(request)
        limiter: FailureLimiter = request.app.state.math_gate_limiter
        ip = client_ip(request)
        if limiter.is_blocked(ip):
            return templates.TemplateResponse(
                request,
                "error.html",
                {"status_code": 429, "message": "請求過於頻繁，請稍後再試。"},
                status_code=429,
            )
        limiter.record_failure(ip)

        challenge_key = _math_gate_key(token) + ":challenge"
        problem = request.session.get(challenge_key)
        submitted = _form_text(form.get("answer")).strip()
        correct = (
            isinstance(problem, dict)
            and isinstance(problem.get("answer"), int)
            and submitted.isdecimal()
            and len(submitted) <= 3
            and int(submitted) == problem["answer"]
        )
        if correct:
            now = app.state.clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            request.session[_math_gate_key(token)] = now.isoformat()
            request.session.pop(challenge_key, None)
            return RedirectResponse(f"/e/{token}", status_code=303)

        left, right = _math_problem(request)
        request.session[challenge_key] = {
            "left": left,
            "right": right,
            "answer": left + right,
        }
        return templates.TemplateResponse(
            request,
            "event_math_gate.html",
            {
                "event": events.present_event(event, settings.timezone),
                "left": left,
                "right": right,
                "error": "答案不正確，請再試一次。",
            },
            status_code=200,
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
        # Bind signed cookies to the current admin password so rotating the
        # password immediately invalidates existing stateless sessions.
        secret_key=hmac.new(
            settings.session_secret.encode("utf-8"),
            settings.admin_password.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
        always_secure=settings.cookie_secure,
    )
    install_request_logging(app, logger)

    return app
