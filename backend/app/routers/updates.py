"""What the refresh pipeline did, so a stale corpus is visible rather than assumed."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()

UPDATES_DIR = Path(__file__).resolve().parents[3] / "data" / "updates"
MAX_REPORTS = 60


def _reports() -> list[dict]:
    if not UPDATES_DIR.exists():
        return []
    reports = []
    for path in sorted(UPDATES_DIR.glob("*.json"), reverse=True)[:MAX_REPORTS]:
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            logger.warning("unreadable update report: %s", path.name)
    return reports


@router.get("/api/updates")
async def list_updates(limit: int = 10) -> dict:
    reports = _reports()[:limit]
    return {
        "latest": reports[0]["date"] if reports else None,
        "count": len(reports),
        "reports": reports,
    }


@router.get("/api/updates/{report_date}")
async def get_update(report_date: str) -> dict:
    path = UPDATES_DIR / f"{report_date}.json"
    markdown = UPDATES_DIR / f"{report_date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="bunday sanadagi hisobot yo'q")
    report = json.loads(path.read_text(encoding="utf-8"))
    if markdown.exists():
        report["markdown"] = markdown.read_text(encoding="utf-8")
    return report
