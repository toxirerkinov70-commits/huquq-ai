"""Run the corpus refresh on a schedule.

Every job takes a Qdrant snapshot first. An update that goes wrong can then be rolled
back instead of re-embedding the corpus, which is the difference between a bad afternoon
and a bad week.

The work runs as a subprocess rather than inside the event loop: a crawl holds the CPU
for minutes at a time and must not be able to take the API down with it.

This module is also a program. ``python -m backend.app.scheduler`` runs the jobs and
nothing else, which is how it is deployed: inside the API process it would start once per
uvicorn worker, so four workers meant four simultaneous crawls of a site that asks for
twenty seconds between requests.
"""

import logging
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .db import sqlite

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Tashkent")
ROOT = Path(__file__).resolve().parents[2]
UPDATE_SCRIPT = ROOT / "parser" / "run_update.py"
BACKUP_SCRIPT = ROOT / "scripts" / "backup.py"

# conversations are kept no longer than the longest plan allows, and the usage ledger
# outlives them because it is what invoices are reconstructed from
MESSAGE_RETENTION_DAYS = 1095
USAGE_RETENTION_DAYS = 1460


def _run(label: str, command: list[str]) -> None:
    logger.info("scheduled job %s starting: %s", label, " ".join(command[-3:]))
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=6 * 3600)
    except subprocess.TimeoutExpired:
        logger.error("scheduled job %s timed out", label)
        return
    if result.returncode == 0:
        logger.info("scheduled job %s finished", label)
    else:
        # exit code 2 is the safety limit tripping, not a crash; both need a human
        logger.error(
            "scheduled job %s exited %s: %s", label, result.returncode, result.stderr[-500:]
        )


def _snapshot() -> None:
    # a python script rather than a shell one, so the same job runs on the windows
    # development machine and in the linux container
    _run("backup", [sys.executable, str(BACKUP_SCRIPT)])


def _update(label: str, *flags: str) -> None:
    _snapshot()
    _run(label, [sys.executable, str(UPDATE_SCRIPT), *flags])


def daily() -> None:
    """What was published today, plus the codes, which carry the most answers."""
    _update("daily", "--window", "today", "--check-codes")


def weekly() -> None:
    """Covers the days a daily run was missed."""
    _update("weekly", "--window", "week")


def monthly() -> None:
    """Re-hash everything indexed; catches silent edits the feed never announced."""
    _update("monthly", "--check-all")


def retention() -> None:
    """Delete what the privacy notice says is deleted."""
    try:
        removed = sqlite.purge_old_data(MESSAGE_RETENTION_DAYS, USAGE_RETENTION_DAYS)
    except Exception:
        logger.exception("retention pass failed")
        return
    logger.info(
        "retention: %s session(s), %s message(s), %s usage row(s) removed",
        removed["sessions"],
        removed["messages"],
        removed["usage_events"],
    )


def build_scheduler() -> AsyncIOScheduler:
    # a trigger built ahead of time fixes its own timezone from the system clock, which
    # in the container is UTC; the scheduler's setting does not reach back into it, so
    # every trigger is told the zone explicitly or the daily run lands five hours late
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        daily, CronTrigger(hour=6, minute=0, timezone=TIMEZONE), id="daily", replace_existing=True
    )
    scheduler.add_job(
        weekly,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=TIMEZONE),
        id="weekly",
        replace_existing=True,
    )
    scheduler.add_job(
        monthly,
        CronTrigger(day=1, hour=2, minute=0, timezone=TIMEZONE),
        id="monthly",
        replace_existing=True,
    )
    scheduler.add_job(
        retention,
        CronTrigger(hour=4, minute=30, timezone=TIMEZONE),
        id="retention",
        replace_existing=True,
    )
    return scheduler


def start() -> AsyncIOScheduler | None:
    if not settings.enable_scheduler:
        logger.info("scheduler disabled in this process")
        return None
    scheduler = build_scheduler()
    scheduler.start()
    logger.info(
        "scheduler started: %s", ", ".join(f"{job.id} {job.next_run_time}" for job in scheduler.get_jobs())
    )
    return scheduler


def main() -> int:
    """Entry point for the dedicated scheduler container."""
    import asyncio

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    sqlite.init_db()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info(
        "scheduler process started: %s",
        ", ".join(f"{job.id} {job.next_run_time}" for job in scheduler.get_jobs()),
    )

    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler process stopping")
    finally:
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
