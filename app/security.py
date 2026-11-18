"""Admin authentication, CSRF, and request guards."""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

ADMIN_SESSION_KEY = "admin_authenticated_at"
CSRF_SESSION_KEY = "csrf_token"
ADMIN_SESSION_HOURS = 12


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def verify_csrf(request: Request, submitted: str | None) -> None:
    expected = request.session.get(CSRF_SESSION_KEY, "")
    if (
        not submitted
        or not expected
        or not hmac.compare_digest(expected.encode("utf-8"), submitted.encode("utf-8"))
    ):
        raise HTTPException(
            status_code=400, detail="表單已失效，請重新整理頁面後再試。"
        )


async def csrf_protected_form(request: Request):
    """Read a form body and reject it unless it carries this session's token."""
    form = await request.form()
    token = form.get("csrf_token")
    verify_csrf(request, token if isinstance(token, str) else None)
    return form


def password_matches(submitted: str, expected: str) -> bool:
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))


def clock_of(request: Request) -> datetime:
    return request.app.state.clock()


def sign_in_admin(request: Request) -> None:
    request.session[ADMIN_SESSION_KEY] = clock_of(request).isoformat()


def sign_out_admin(request: Request) -> None:
    request.session.clear()


def admin_is_authenticated(request: Request) -> bool:
    raw = request.session.get(ADMIN_SESSION_KEY)
    if not raw:
        return False
    try:
        signed_in_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        request.session.pop(ADMIN_SESSION_KEY, None)
        return False
    if signed_in_at.tzinfo is None:
        signed_in_at = signed_in_at.replace(tzinfo=timezone.utc)
    if clock_of(request) - signed_in_at >= timedelta(hours=ADMIN_SESSION_HOURS):
        request.session.pop(ADMIN_SESSION_KEY, None)
        return False
    return True


def client_ip(request: Request) -> str:
    # uvicorn's proxy-header handling rewrites request.client from
    # X-Forwarded-For only when the peer is a trusted proxy. Trusting the
    # header directly here would let any client pick its own rate-limit key.
    if request.client is None:
        return "unknown"
    return request.client.host


def install_admin_guard(app) -> None:
    """Redirect signed-out visitors away from every /admin route but login."""

    @app.middleware("http")
    async def guard_admin(request: Request, call_next):
        path = request.url.path
        if path.startswith("/admin") and path != "/admin/login":
            if not admin_is_authenticated(request):
                return RedirectResponse("/admin/login", status_code=303)
        return await call_next(request)
