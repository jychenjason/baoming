"""Signed cookie sessions with per-request security flags.

Adapted from ``starlette.middleware.sessions.SessionMiddleware`` (MIT).
Starlette decides the ``Secure`` flag once, at startup; behind a
TLS-terminating proxy the scheme is only known per request, so this middleware
sets the flag from the request instead.
"""

from __future__ import annotations

import json
from base64 import b64decode, b64encode

from itsdangerous import BadSignature, TimestampSigner
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.sessions import Session
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_MAX_AGE_SECONDS = 24 * 60 * 60


def is_https(scope: Scope, headers: Headers | None = None) -> bool:
    if scope.get("scheme") == "https":
        return True
    forwarded = (headers or Headers(scope=scope)).get("x-forwarded-proto", "")
    return forwarded.split(",", 1)[0].strip().lower() == "https"


class SessionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        max_age: int = SESSION_MAX_AGE_SECONDS,
        session_cookie: str = "session",
        same_site: str = "lax",
        always_secure: bool = False,
    ) -> None:
        self.app = app
        self.signer = TimestampSigner(secret_key)
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.same_site = same_site
        self.always_secure = always_secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        headers = Headers(scope=scope)
        initial_session_was_empty = True

        cookie = connection.cookies.get(self.session_cookie)
        if cookie:
            try:
                payload = self.signer.unsign(
                    cookie.encode("utf-8"), max_age=self.max_age
                )
                scope["session"] = Session(json.loads(b64decode(payload)))
                initial_session_was_empty = False
            except (BadSignature, ValueError):
                scope["session"] = Session()
        else:
            scope["session"] = Session()

        secure = self.always_secure or is_https(scope, headers)
        security_flags = f"HttpOnly; SameSite={self.same_site}"
        if secure:
            security_flags += "; Secure"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: Session = scope["session"]
                message.setdefault("headers", [])
                response_headers = MutableHeaders(scope=message)
                if session.accessed:
                    response_headers.add_vary_header("Cookie")
                if session.modified and session:
                    data = b64encode(
                        json.dumps(session, separators=(",", ":")).encode("utf-8")
                    )
                    signed = self.signer.sign(data).decode("utf-8")
                    response_headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}={signed}; Path=/; "
                        f"Max-Age={self.max_age}; {security_flags}",
                    )
                elif session.modified and not initial_session_was_empty:
                    response_headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}=null; Path=/; "
                        "Expires=Thu, 01 Jan 1970 00:00:00 GMT; "
                        f"{security_flags}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
