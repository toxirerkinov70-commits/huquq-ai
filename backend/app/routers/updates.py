"""What the refresh pipeline did, so a stale corpus is visible rather than assumed."""

import json
import re
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..services import auth
from ..services.auth import Principal

logger = structlog.get_logger(__name__)

router = APIRouter()

UPDATES_DIR = Path(__file__).resolve().parents[3] / "data" / "updates"
MAX_REPORTS = 60
# the report name goes into a filesystem path, so it is matched rather than trusted
REPORT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _reports() -> list[dict]:
    if not UPDATES_DIR.exists():
        return []
    reports = []
    for path in sorted(UPDATES_DIR.glob("*.json"), reverse=True)[:MAX_REPORTS]:
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            logger.warning("unreadable update report", file=path.name)
    return reports


@router.get("/api/updates")
async def list_updates(limit: int = 10) -> dict:
    """Public on purpose: "when was this corpus last refreshed" is a trust signal."""
    limit = max(1, min(limit, MAX_REPORTS))
    reports = _reports()[:limit]
    return {
        "latest": reports[0]["date"] if reports else None,
        "count": len(reports),
        "reports": reports,
    }


@router.get("/api/updates/{report_date}")
async def get_update(
    report_date: str, _: Principal = Depends(auth.current_principal)
) -> dict:
    if not REPORT_DATE_RE.match(report_date):
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_date", "message": "Sana YYYY-MM-DD shaklida bo'lishi kerak."},
        )
    path = UPDATES_DIR / f"{report_date}.json"
    markdown = UPDATES_DIR / f"{report_date}.md"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": "Bunday sanadagi hisobot yo'q."}
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    if markdown.exists():
        report["markdown"] = markdown.read_text(encoding="utf-8")
    return report
