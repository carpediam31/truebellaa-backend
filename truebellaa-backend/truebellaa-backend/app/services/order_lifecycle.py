"""
Order lifecycle: move an order between states, cancel it, refund it.

The allowed transitions are declared in one place so the rules can't drift
between the API, the admin panel and the webhook. Anything not listed is
rejected — that's what stops a delivered order being silently moved back to
pending, or a cancelled order being shipped.

Cancelling returns reserved or sold stock to the shelf, which the old code
never did: a cancelled order used to keep its stock consumed forever.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import InventoryMovement, ProductVariant
from app.models.order import Order, OrderStatusHistory
from app.services.audit_service import log_action

logger = logging.getLogger("app.orders")

# what each status may become next
TRANSITIONS: dict[str, set[str]] = {
    "pending_payment": {"paid", "cancelled"},
    "paid":            {"processing", "shipped", "cancelled", "refunded"},
    "processing":      {"shipped", "cancelled", "refunded"},
    "shipped":         {"delivered", "returned"},
    "delivered":       {"returned", "refunded"},
    "returned":        {"refunded"},
    "cancelled":       set(),      # terminal
    "refunded":        set(),      # terminal
}

# Statuses where stock is still "held" by the order and must be given back
# if it is cancelled. Once returned/refunded the stock was already released.
STOCK_HELD_IN = {"pending_payment", "paid", "processing", "shipped"}


def can_move(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def _consume_reservation(db: Session, order: Order) -> None:
    """
    Turn a checkout reservation into an actual sale: drop both the hold and
    the on-hand count. Mirrors what order_service does when Razorpay
    confirms payment, so both paths leave inventory in the same state.
    """
    for item in order.items:
        variant = db.get(ProductVariant, item.variant_id)
        if not variant:
            continue
        variant.stock_reserved = max(0, (variant.stock_reserved or 0) - item.quantity)
        variant.stock_on_hand = max(0, (variant.stock_on_hand or 0) - item.quantity)
        db.add(InventoryMovement(
            tenant_id=order.tenant_id, variant_id=variant.id,
            change_qty=-item.quantity, reason="sale",
            reference=f"paid:{order.order_number}",
        ))


def _release_stock(db: Session, order: Order, reason: str) -> int:
    """
    Put an order's units back on the shelf.

    pending_payment holds stock as a *reservation*; anything later has
    already converted it into a real deduction from stock_on_hand. Undoing
    the right one matters — undo the wrong one and inventory drifts.
    """
    released = 0
    for item in order.items:
        variant = db.get(ProductVariant, item.variant_id)
        if not variant:
            continue
        if order.status == "pending_payment":
            variant.stock_reserved = max(0, (variant.stock_reserved or 0) - item.quantity)
        else:
            variant.stock_on_hand = (variant.stock_on_hand or 0) + item.quantity
        db.add(InventoryMovement(
            tenant_id=order.tenant_id, variant_id=variant.id,
            change_qty=item.quantity, reason="release" if order.status == "pending_payment" else "return",
            reference=f"{reason}:{order.order_number}",
        ))
        released += item.quantity
    return released


def change_status(db: Session, order: Order, target: str, *, staff_id: int | None,
                  staff_name: str | None, note: str | None = None,
                  meta: dict | None = None) -> Order:
    """Move an order to `target`, enforcing the transition table."""
    meta = meta or {}
    current = order.status
    if current == target:
        raise HTTPException(status_code=409, detail=f"Order is already {target}")
    if not can_move(current, target):
        allowed = ", ".join(sorted(TRANSITIONS.get(current, set()))) or "nothing (final state)"
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move an order from '{current}' to '{target}'. Allowed: {allowed}",
        )

    # Moving into "paid" must convert the checkout's RESERVATION into a real
    # sale, exactly as the payment webhook does. Without this the reservation
    # is never consumed, and a later cancel would add stock back that was
    # never taken away — inventing inventory out of nothing.
    if target == "paid" and current == "pending_payment":
        _consume_reservation(db, order)

    # Give stock back before the status flips, because _release_stock reads
    # the OLD status to decide reserved-vs-on-hand.
    released = 0
    if target in ("cancelled", "returned") and current in STOCK_HELD_IN:
        released = _release_stock(db, order, target)

    order.status = target
    # The orders table has no delivered_at column; order_status_history is
    # the record of when each transition happened, so don't duplicate it.

    db.add(OrderStatusHistory(
        tenant_id=order.tenant_id, order_id=order.id, from_status=current,
        to_status=target, note=note, changed_by=staff_id,
    ))
    summary = f"Order {order.order_number}: {current} -> {target}"
    if released:
        summary += f" ({released} unit(s) returned to stock)"
    log_action(db, tenant_id=order.tenant_id, actor_type="staff" if staff_id else "system",
               actor_id=staff_id, actor_name=staff_name, action=f"order.{target}",
               entity_type="order", entity_id=order.id, entity_label=order.order_number,
               summary=summary, old_values={"status": current}, new_values={"status": target},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    logger.info("%s", summary)
    return order


def get_order_or_404(db: Session, tenant_id: int, public_id: str) -> Order:
    order = db.execute(
        select(Order).where(Order.tenant_id == tenant_id, Order.public_id == public_id)
        .options(selectinload(Order.items))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
