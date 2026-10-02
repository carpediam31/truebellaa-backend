"""
Release stock held by abandoned checkouts.

Checkout reserves stock (stock_reserved += qty) and payment converts that
reservation into a sale. But a shopper who reaches the payment screen and
walks away leaves the order in `pending_payment` FOREVER — and its stock
reserved forever with it. Over time real, sellable inventory silently
disappears and products show as out of stock.

This releases reservations for pending_payment orders older than
--minutes (default 60) and marks those orders cancelled.

    python scripts/release_stale_reservations.py                 # preview
    python scripts/release_stale_reservations.py --apply
    python scripts/release_stale_reservations.py --minutes 30 --apply

Run it on a schedule (Windows Task Scheduler / cron) every 15-30 minutes.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import WriteSession          # noqa: E402
from app.models.catalog import ProductVariant       # noqa: E402
from app.models.order import Order                  # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv
    minutes = 60
    if "--minutes" in sys.argv:
        minutes = int(sys.argv[sys.argv.index("--minutes") + 1])

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    db = WriteSession()

    stale = db.execute(
        select(Order).where(Order.status == "pending_payment", Order.created_at < cutoff)
    ).scalars().all()

    if not stale:
        print(f"No pending_payment orders older than {minutes} min. Nothing to release.")
        return 0

    print(f"{len(stale)} abandoned order(s) older than {minutes} min:\n")
    released = 0
    for order in stale:
        age = datetime.utcnow() - order.created_at if order.created_at else None
        print(f"  {order.order_number}  ({int(age.total_seconds() // 60) if age else '?'} min old)")
        for item in order.items:
            variant = db.get(ProductVariant, item.variant_id)
            if not variant:
                continue
            give_back = min(item.quantity, variant.stock_reserved or 0)
            print(f"      {variant.sku}: release {give_back} "
                  f"(reserved {variant.stock_reserved} -> {(variant.stock_reserved or 0) - give_back})")
            if apply:
                variant.stock_reserved = max(0, (variant.stock_reserved or 0) - give_back)
            released += give_back
        if apply:
            order.status = "cancelled"

    print()
    if apply:
        db.commit()
        print(f"Released {released} unit(s) and cancelled {len(stale)} abandoned order(s).")
    else:
        print(f"Would release {released} unit(s) from {len(stale)} order(s). "
              f"Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
