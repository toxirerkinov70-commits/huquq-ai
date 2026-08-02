"""Operator view: who is using the service, what it costs, and who to upgrade or stop.

Switched off entirely unless ADMIN_API_KEY is set, and it answers 404 rather than 401 in
that case so an unconfigured deployment does not advertise that these paths exist.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..db import sqlite
from ..models import PlanChangeRequest, StatusChangeRequest
from ..services import auth, plans
from ..services.auth import Principal

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def stats(days: int = 30, _: Principal = Depends(auth.require_admin)):
    days = max(1, min(days, 365))
    summary = sqlite.platform_summary(days)
    cost_usd = float(summary["totals"].get("cost_usd") or 0)
    summary["totals"]["cost_uzs"] = round(cost_usd * settings.usd_to_uzs, 2)

    # what the same traffic would have earned at list price, so the margin is visible
    revenue_uzs = sum(
        plans.get(plan).price_uzs * count
        for plan, count in summary["users_by_plan"].items()
        if plans.get(plan).price_uzs
    )
    summary["mrr_uzs"] = revenue_uzs
    summary["gross_margin_uzs"] = round(revenue_uzs - summary["totals"]["cost_uzs"], 2)
    return summary


@router.get("/users")
async def users(
    limit: int = 100, offset: int = 0, _: Principal = Depends(auth.require_admin)
):
    limit = max(1, min(limit, 500))
    return {"users": sqlite.list_users(limit, offset)}


@router.get("/users/{user_id}")
async def user_detail(user_id: str, _: Principal = Depends(auth.require_admin)):
    user = sqlite.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {
        "user": user,
        "plan": plans.for_user(user).as_dict(),
        "usage": sqlite.usage_summary(user_id, 30),
        "api_keys": sqlite.list_api_keys(user_id),
    }


@router.post("/users/plan")
async def change_plan(payload: PlanChangeRequest, _: Principal = Depends(auth.require_admin)):
    """Applied by hand after a payment clears.

    Payment providers are not wired in yet; when Payme or Click is connected, its
    callback calls exactly this path instead of an operator doing it.
    """
    if payload.plan not in plans.PLANS:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_plan", "message": f"Bunday tarif yo'q: {payload.plan}"},
        )
    if sqlite.get_user(payload.user_id) is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    user = sqlite.set_plan(payload.user_id, payload.plan, payload.expires_at)
    logger.info(
        "plan changed", user_id=payload.user_id, plan=payload.plan, expires=payload.expires_at
    )
    return {"user": user}


@router.post("/users/status")
async def change_status(
    payload: StatusChangeRequest, _: Principal = Depends(auth.require_admin)
):
    if sqlite.get_user(payload.user_id) is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    user = sqlite.set_status(payload.user_id, payload.status)
    logger.info("status changed", user_id=payload.user_id, status=payload.status)
    return {"user": user}


@router.post("/users/service")
async def create_service_account(
    label: str, plan: str = "biznes", _: Principal = Depends(auth.require_admin)
):
    """A machine account with its key, for an integration customer."""
    if plan not in plans.PLANS:
        raise HTTPException(status_code=400, detail={"error": "unknown_plan"})
    user = sqlite.create_user(kind="service", plan=plan, label=label)
    raw, key_hash, prefix = auth.new_api_key()
    key_id = sqlite.create_api_key(user["id"], key_hash, prefix, label)
    logger.info("service account created", user_id=user["id"], plan=plan, label=label)
    return {"user": user, "api_key": raw, "key_id": key_id, "prefix": prefix}


@router.post("/retention/run")
async def run_retention(
    message_days: int = 1095, usage_days: int = 1460, _: Principal = Depends(auth.require_admin)
):
    removed = sqlite.purge_old_data(message_days, usage_days)
    logger.info("retention run by hand", **removed)
    return {"deleted": removed}
