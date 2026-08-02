from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from . import logging_setup
from . import scheduler as scheduler_service
from .config import settings
from .db import sqlite
from .middleware import (
    BodySizeLimitMiddleware,
    PopupOpenerMiddleware,
    RequestContextMiddleware,
)
from .routers import account, admin, auth as auth_router, chat, orders, search, updates
from .services import plans, usage
from .services.llm import LLMClient
from .services.retrieval import Retriever

logging_setup.configure()
logger = structlog.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "frontend"
LEGAL_DIR = ROOT / "docs" / "legal"

LEGAL_DOCUMENTS = {
    "oferta": "oferta.md",
    "maxfiylik": "maxfiylik.md",
    "saqlash": "saqlash.md",
}


def _rate_limit_key(request: Request) -> str:
    """Limit per account when there is one, per address otherwise.

    Behind a proxy every request shares one address, so keying on the address alone
    would let one heavy user exhaust the allowance for everybody.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, default_limits=[settings.rate_limit])


def _cors_origins() -> list[str]:
    if settings.allow_public_cors:
        logger.warning("CORS is open to every origin — every request spends API quota")
        return ["*"]
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    sqlite.init_db()
    app.state.retriever = Retriever()
    app.state.llm = LLMClient()
    app.state.scheduler = scheduler_service.start()
    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY is empty — answering will fail")
    if settings.environment == "production" and not settings.auth_secret:
        logger.warning("AUTH_SECRET is not set in production; tokens rest on a generated file")
    logger.info(
        "started",
        collection=settings.qdrant_collection,
        environment=settings.environment,
        plans=list(plans.PLANS),
        scheduler=app.state.scheduler is not None,
    )
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)
        await app.state.retriever.close()
        await app.state.llm.close()


app = FastAPI(title="Huquq AI", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter

# added last runs first: the request id is bound before anything else can log
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Admin-Key", "X-Request-ID"],
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(PopupOpenerMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(auth_router.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(updates.router)
app.include_router(account.router)
app.include_router(orders.router)
app.include_router(admin.router)


@app.exception_handler(usage.QuotaExceeded)
async def quota_exceeded(request: Request, exc: usage.QuotaExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": exc.as_detail()},
        headers={"Retry-After": str(exc.reset_seconds)},
    )


@app.exception_handler(usage.FeatureNotInPlan)
async def feature_not_in_plan(request: Request, exc: usage.FeatureNotInPlan) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": exc.as_detail()})


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return _rate_limit_exceeded_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error": "internal_error",
                "message": "Ichki xatolik. Qaytadan urinib ko'ring.",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    qdrant_ok = False
    points = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            headers = (
                {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else None
            )
            response = await client.get(
                f"{settings.qdrant_url}/collections/{settings.qdrant_collection}",
                headers=headers,
            )
            qdrant_ok = response.status_code == 200
            if qdrant_ok:
                points = response.json()["result"].get("points_count")
    except httpx.HTTPError as exc:
        logger.error("qdrant health check failed", error=str(exc))

    database_ok = True
    try:
        with sqlite.connect() as connection:
            connection.execute("SELECT 1")
    except Exception as exc:
        database_ok = False
        logger.error("database health check failed", error=str(exc))

    # an empty key is a configuration fault that otherwise only shows up as a 403 on
    # the first question somebody asks
    llm_ok = bool(settings.gemini_api_key)
    healthy = qdrant_ok and database_ok and llm_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "qdrant": qdrant_ok,
            "database": database_ok,
            "llm_key": llm_ok,
            "collection": settings.qdrant_collection,
            "points": points,
            "environment": settings.environment,
        },
    )


@app.get("/api/legal/{name}")
async def legal(name: str) -> dict:
    """The offer and the privacy notice, served from the repository they live in."""
    filename = LEGAL_DOCUMENTS.get(name)
    if filename is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    path = LEGAL_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"name": name, "markdown": path.read_text(encoding="utf-8")}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
