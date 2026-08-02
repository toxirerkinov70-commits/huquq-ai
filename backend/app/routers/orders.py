"""Buying a plan, up to the point where money would change hands.

No payment provider is connected yet, so an order stops at ``pending`` and an operator
confirms it. That is deliberate rather than unfinished: everything around the payment —
the order, the price, the term, the activation, the expiry, the receipt the customer can
see — is the part that takes thought, and it is done. When Payme or Click is wired in,
its callback calls ``_activate`` and nothing else changes.
"""

from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..db import sqlite
from ..models import OrderInfo, OrderRequest, PaymentMethod
from ..services import auth, plans
from ..services.auth import Principal

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["orders"])

# what the checkout screen offers. "available" is false until the integration exists,
# and the client greys those out rather than pretending they work
PAYMENT_METHODS = [
    PaymentMethod(
        key="payme",
        name="Payme",
        description="Karta orqali to'lov",
        available=False,
    ),
    PaymentMethod(
        key="click",
        name="Click",
        description="Karta orqali to'lov",
        available=False,
    ),
    PaymentMethod(
        key="uzum",
        name="Uzum Bank",
        description="Karta orqali to'lov",
        available=False,
    ),
    PaymentMethod(
        key="transfer",
        name="Bank o'tkazmasi",
        description="Hisob-faktura asosida, yuridik shaxslar uchun",
        available=True,
    ),
]

# a longer term is cheaper per month, which is the usual reason to choose one
TERM_DISCOUNTS = {1: 0.0, 3: 0.05, 6: 0.10, 12: 0.20}


def price_for(plan_key: str, months: int) -> int:
    plan = plans.get(plan_key)
    discount = TERM_DISCOUNTS.get(months, 0.0)
    raw = plan.price_uzs * months * (1 - discount)
    # rounded to the nearest thousand so the amount reads like a price
    return int(round(raw / 1000.0) * 1000)


def _info(order: dict) -> OrderInfo:
    return OrderInfo(
        id=order["id"],
        plan=order["plan"],
        plan_name=plans.get(order["plan"]).name,
        months=order["months"],
        amount_uzs=order["amount_uzs"],
        provider=order.get("provider"),
        status=order["status"],
        created_at=order.get("created_at"),
        paid_at=order.get("paid_at"),
        note=order.get("note"),
    )


@router.get("/payment-methods", response_model=list[PaymentMethod])
async def payment_methods():
    return PAYMENT_METHODS


@router.get("/plans/{plan_key}/quote")
async def quote(plan_key: str, _: Principal = Depends(auth.current_principal)):
    """Every term with its price, so the checkout screen does no arithmetic of its own."""
    plan = plans.get(plan_key)
    if not plan.is_purchasable:
        raise HTTPException(
            status_code=400,
            detail={"error": "not_purchasable", "message": "Bu tarifni sotib bo'lmaydi."},
        )
    options = []
    for months, discount in TERM_DISCOUNTS.items():
        total = price_for(plan_key, months)
        options.append(
            {
                "months": months,
                "amount_uzs": total,
                "per_month_uzs": int(round(total / months)),
                "discount_percent": int(discount * 100),
            }
        )
    return {"plan": plan.as_dict(), "options": options}


@router.post("/orders", response_model=OrderInfo)
async def create_order(
    payload: OrderRequest, principal: Principal = Depends(auth.current_principal)
):
    plan = plans.get(payload.plan)
    if plan.key != payload.plan or not plan.is_purchasable:
        raise HTTPException(
            status_code=400,
            detail={"error": "not_purchasable", "message": "Bunday tarif sotuvda yo'q."},
        )
    if payload.months not in TERM_DISCOUNTS:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_term", "message": "Muddat 1, 3, 6 yoki 12 oy bo'lishi mumkin."},
        )
    if payload.provider and payload.provider not in {m.key for m in PAYMENT_METHODS}:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_provider", "message": "To'lov usuli tanilmadi."},
        )

    # one open order at a time, or a customer who clicks twice owes twice
    open_orders = [o for o in sqlite.list_orders(principal.id, status="pending")]
    if open_orders:
        return _info(open_orders[0])

    order = sqlite.create_order(
        principal.id, plan.key, payload.months, price_for(plan.key, payload.months), payload.provider
    )
    logger.info(
        "order created",
        order_id=order["id"],
        user_id=principal.id,
        plan=plan.key,
        months=payload.months,
        amount=order["amount_uzs"],
    )
    return _info(order)


@router.get("/orders", response_model=list[OrderInfo])
async def my_orders(principal: Principal = Depends(auth.current_principal)):
    return [_info(order) for order in sqlite.list_orders(principal.id)]


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str, principal: Principal = Depends(auth.current_principal)
):
    order = sqlite.get_order(order_id)
    if order is None or order["user_id"] != principal.id:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if order["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail={"error": "not_pending", "message": "Bu buyurtmani bekor qilib bo'lmaydi."},
        )
    sqlite.set_order_status(order_id, "cancelled")
    return {"cancelled": order_id}


def activate(order: dict) -> dict:
    """Turn a paid order into a live subscription.

    Extends from whichever is later — today or the current expiry — so renewing early
    adds to the term instead of throwing away what is left of it.
    """
    user = sqlite.get_user(order["user_id"])
    start = date.today()
    current = (user or {}).get("plan_expires_at")
    if current:
        try:
            existing = date.fromisoformat(current[:10])
            if existing > start and (user or {}).get("plan") == order["plan"]:
                start = existing
        except ValueError:
            pass
    expires = start + timedelta(days=30 * order["months"])
    sqlite.set_plan(order["user_id"], order["plan"], expires.isoformat())
    updated = sqlite.set_order_status(order["id"], "paid")
    logger.info(
        "plan activated",
        order_id=order["id"],
        user_id=order["user_id"],
        plan=order["plan"],
        expires=expires.isoformat(),
    )
    return updated or order


@router.post("/admin/orders/{order_id}/confirm", response_model=OrderInfo)
async def confirm_order(order_id: str, _: Principal = Depends(auth.require_admin)):
    """What a payment callback will do once there is one to receive it."""
    order = sqlite.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if order["status"] == "paid":
        return _info(order)
    return _info(activate(order))


@router.get("/admin/orders", response_model=list[OrderInfo])
async def all_orders(status: str | None = None, _: Principal = Depends(auth.require_admin)):
    return [_info(order) for order in sqlite.list_orders(status=status)]
