"""Anonymous browser identity and bounded admission at the HTTP boundary."""

import hashlib
import re
import secrets
from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import TooManyRequests
from .limits import MemoryLimits
from .settings import Settings

COOKIE = "oxhack_session"
SESSION_AGE = 30 * 24 * 60 * 60


class BrowserSecurity:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        # ponytail: request bursts are per API process; durable paid-call budgets
        # live in the repo. Use an edge limiter before scaling the public API.
        self.limits = MemoryLimits()
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = request.cookies.get(COOKIE, "")
        fresh = re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None
        if fresh:
            token = secrets.token_urlsafe(32)
        scope.setdefault("state", {})["session_id"] = hashlib.sha256(token.encode()).hexdigest()
        peer = self.peer(request)
        scope["state"]["client_id"] = hashlib.sha256(peer.encode()).hexdigest()

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "same-origin"
                if fresh:
                    cookie = Response()
                    cookie.set_cookie(
                        COOKIE,
                        token,
                        max_age=SESSION_AGE,
                        httponly=True,
                        samesite="lax",
                        secure=self.settings.session_cookie_secure or request.url.scheme == "https",
                        path="/",
                    )
                    headers.append("set-cookie", cookie.headers["set-cookie"])
            await send(message)

        try:
            if request.url.path != "/api/health":
                self.limits.consume(f"ip:{peer}", self.settings.requests_per_minute * 3, 60)
                self.limits.consume(f"session:{token}", self.settings.requests_per_minute, 60)
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    self.limits.consume(f"write:{peer}", self.settings.writes_per_minute, 60)
                    origin = request.headers.get("origin")
                    cross_site = request.headers.get("sec-fetch-site") in {
                        "cross-site",
                        "same-site",
                    }
                    if origin:
                        try:
                            parsed = urlsplit(origin)
                            cross_site |= parsed.scheme not in {
                                "http",
                                "https",
                            } or parsed.netloc != request.headers.get("host")
                        except ValueError:
                            cross_site = True
                    if cross_site:
                        await JSONResponse(
                            {"detail": "Cross-site requests are not allowed."}, status_code=403
                        )(scope, receive, secure_send)
                        return
            if (
                request.url.path != "/api/health"
                and self.active >= self.settings.max_active_requests
            ):
                await JSONResponse(
                    {"detail": "The server is busy. Please try again shortly."},
                    status_code=503,
                    headers={"Retry-After": "5"},
                )(scope, receive, secure_send)
                return
        except TooManyRequests as exc:
            await JSONResponse(
                {"detail": exc.detail},
                status_code=429,
                headers={"Retry-After": str(exc.retry_after)},
            )(scope, receive, secure_send)
            return
        self.active += 1
        try:
            await self.app(scope, receive, secure_send)
        finally:
            self.active -= 1

    def peer(self, request: Request) -> str:
        """The reader's IP: the connection's peer, normalized by Uvicorn's trusted proxy
        handling, or OXHACK_CLIENT_IP_HEADER's address behind a proxy that overwrites
        it. Accepting a header the caller controls, such as X-Forwarded-For through an
        external rewrite, would let callers bypass quotas."""
        peer = request.client.host if request.client else "unknown"
        header = self.settings.client_ip_header
        if header is None:
            return peer
        try:
            return str(ip_address(request.headers.get(header, "").split(",")[0].strip()))
        except ValueError:
            return peer
