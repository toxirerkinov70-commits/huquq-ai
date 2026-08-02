"""Edge concerns: request identity, access logging, and a ceiling on request size.

These are pure ASGI middleware rather than ``BaseHTTPMiddleware`` subclasses because the
chat endpoint streams: BaseHTTPMiddleware buffers the response through a queue in another
task, which both delays the first token and moves the body out of the context where the
request id and the usage meter were bound.
"""

import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = b"x-request-id"


class RequestContextMiddleware:
    """Give every request an id, bind it to the log context, and record how it went."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = headers.get(REQUEST_ID_HEADER, b"").decode() or uuid.uuid4().hex[:16]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=scope.get("path"),
            method=scope.get("method"),
        )
        scope.setdefault("state", {})["request_id"] = request_id

        started = time.monotonic()
        status_code = {"value": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code["value"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((REQUEST_ID_HEADER, request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = int((time.monotonic() - started) * 1000)
            path = scope.get("path", "")
            # static assets would otherwise be most of the log
            if path.startswith("/api") or path == "/health" or status_code["value"] >= 400:
                logger.info(
                    "request",
                    status=status_code["value"],
                    duration_ms=duration,
                    user_id=scope.get("state", {}).get("user_id"),
                )
            structlog.contextvars.clear_contextvars()


class PopupOpenerMiddleware:
    """Keep this page's handle on the Google sign-in popup it opened.

    ``same-origin-allow-popups`` is what Google's popup flow asks for: it keeps the
    default isolation for every other window while leaving the opener able to address
    the one it launched. Chrome still logs a warning about ``window.closed`` during
    sign-in — that one comes from the policy accounts.google.com sets on its own side
    and is not ours to remove; the sign-in itself completes through postMessage.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append(
                    (b"cross-origin-opener-policy", b"same-origin-allow-popups")
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Reject oversized bodies before a handler allocates memory for them.

    An upload is base64 inside JSON and every accepted file is forwarded to a paid API,
    so the limit is a cost control as much as a memory one.
    """

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes or settings.max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await self._too_large(send)
                    return
            except ValueError:
                pass

        received = 0
        limit = self.max_bytes
        exceeded = {"value": False}

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded["value"] = True
                    # stop feeding the handler; it sees a truncated body and the
                    # response below is what actually reaches the client
                    return {"type": "http.disconnect"}
            return message

        if exceeded["value"]:
            await self._too_large(send)
            return
        await self.app(scope, receive_wrapper, send)

    async def _too_large(self, send: Send) -> None:
        body = (
            b'{"detail":{"error":"payload_too_large",'
            b'"message":"So\'rov hajmi juda katta."}}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
