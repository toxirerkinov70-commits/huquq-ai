"""Accounts, plans, keys and the usage a customer is charged for.

Anonymous sign-up exists so the first question still costs nothing and needs no form,
while every conversation from that point on belongs to somebody. Without it there is no
way to hold a quota, and without a quota there is no product to sell.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..db import sqlite
from ..models import (
    AccountResponse,
    ApiKeyCreated,
    ApiKeyInfo,
    ApiKeyRequest,
    PlanFeatures,
    QuotaStatus,
    UsageResponse,
)
from ..services import auth, otp, plans, usage
from ..services.auth import Principal

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["account"])


def _quota(principal: Principal) -> QuotaStatus:
    return QuotaStatus(**usage.snapshot(principal.id, principal.plan))


@router.get("/account", response_model=AccountResponse)
async def account(principal: Principal = Depends(auth.current_principal)):
    sqlite.touch_user(principal.id)
    keys = (
        [ApiKeyInfo(**row) for row in sqlite.list_api_keys(principal.id)]
        if principal.plan.allow_api_keys
        else []
    )
    phone = principal.user.get("phone")
    return AccountResponse(
        user_id=principal.id,
        kind=principal.user.get("kind", "anon"),
        name=principal.user.get("name"),
        phone=phone,
        phone_display=otp.display_phone(phone) if phone else None,
        email=principal.user.get("email"),
        picture=principal.user.get("picture"),
        plan=PlanFeatures(**principal.plan.as_dict()),
        plan_expires_at=principal.user.get("plan_expires_at"),
        created_at=principal.user.get("created_at"),
        accepted_terms=principal.user.get("terms_version") == settings.terms_version,
        is_owner=principal.plan.key == "owner",
        quota=_quota(principal),
        api_keys=keys,
    )


@router.get("/plans", response_model=list[PlanFeatures])
async def plan_catalogue():
    """The pricing page reads this, so tariffs are never written down in two places."""
    return [PlanFeatures(**item) for item in plans.catalogue()]


@router.get("/quota", response_model=QuotaStatus)
async def quota(principal: Principal = Depends(auth.current_principal)):
    return _quota(principal)


@router.get("/usage", response_model=UsageResponse)
async def account_usage(
    days: int = 30, principal: Principal = Depends(auth.current_principal)
):
    days = max(1, min(days, 365))
    summary = sqlite.usage_summary(principal.id, days)
    cost_usd = float(summary["totals"].get("cost_usd") or 0)
    return UsageResponse(
        window_days=summary["window_days"],
        totals=summary["totals"],
        daily=summary["daily"],
        cost_uzs=round(cost_usd * settings.usd_to_uzs, 2),
    )


@router.post("/account/keys", response_model=ApiKeyCreated)
async def create_key(
    payload: ApiKeyRequest, principal: Principal = Depends(auth.current_principal)
):
    if not principal.plan.allow_api_keys:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "feature_not_in_plan",
                "message": "API kalitlari Biznes tarifida mavjud.",
                "plan": principal.plan.key,
            },
        )
    existing = [row for row in sqlite.list_api_keys(principal.id) if not row["revoked_at"]]
    if len(existing) >= principal.plan.api_keys_max:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "key_limit",
                "message": f"Tarif bo'yicha eng ko'pi {principal.plan.api_keys_max} ta kalit.",
            },
        )
    raw, key_hash, prefix = auth.new_api_key()
    key_id = sqlite.create_api_key(principal.id, key_hash, prefix, payload.name)
    logger.info("api key issued", user_id=principal.id, key_id=key_id)
    row = next(item for item in sqlite.list_api_keys(principal.id) if item["id"] == key_id)
    return ApiKeyCreated(key=raw, **row)


@router.delete("/account/keys/{key_id}")
async def revoke_key(key_id: int, principal: Principal = Depends(auth.current_principal)):
    if not sqlite.revoke_api_key(principal.id, key_id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"revoked": key_id}


@router.delete("/account/data")
async def erase_data(principal: Principal = Depends(auth.current_principal)):
    """Delete every conversation held for this account.

    The privacy notice promises this, so it is an endpoint rather than a support request.
    Usage rows survive: they carry no question text and are what the bill is built from.
    """
    removed = sqlite.delete_user_data(principal.id)
    logger.info("account data erased", user_id=principal.id, **removed)
    return {"deleted": removed}
