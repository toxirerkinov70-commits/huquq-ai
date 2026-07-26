import logging

import httpx
from fastapi import FastAPI

from .config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Huquqiy RAG")


@app.get("/health")
async def health() -> dict:
    qdrant_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.qdrant_url}/collections")
            qdrant_ok = resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("qdrant health check failed: %s", exc)
    return {"status": "ok" if qdrant_ok else "degraded", "qdrant": qdrant_ok}
