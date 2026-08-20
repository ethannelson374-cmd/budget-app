from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.models import RecurringStream, User
from app.services.views import money

CADENCE_MONTHLY_FACTOR: dict[str, Decimal] = {
    "weekly": Decimal("4.345"),
    "biweekly": Decimal("2.1725"),
    "monthly": Decimal("1"),
    "quarterly": Decimal("0.333333"),
    "annual": Decimal("0.083333"),
}


def monthly_equivalent(amount: Decimal, cadence: str) -> Decimal:
    return amount * CADENCE_MONTHLY_FACTOR.get(cadence, Decimal("1"))


def is_subscription(stream: RecurringStream) -> bool:
    if stream.subscription_override is not None:
        return bool(stream.subscription_override)
    return bool(stream.subscription_detected)


def _item(stream: RecurringStream) -> dict[str, object]:
    mask = f"•••• {stream.account.mask_last4}" if stream.account.mask_last4 else None
    return {
        "id": stream.id,
        "display_name": stream.display_name,
        "cadence": stream.cadence,
        "average_amount": money(stream.average_amount),
        "last_amount": money(stream.last_amount),
        "next_expected_date": stream.next_expected_date,
        "price_change_pct": money(stream.price_change_pct) if stream.price_change_pct is not None else None,
        "status": stream.subscription_status,
        "detected": bool(stream.subscription_detected),
        "account": {
            "id": stream.account.id,
            "name": stream.account.name,
            "display_name": f"{stream.account.name} {mask}" if mask else stream.account.name,
            "mask": mask,
            "currency": stream.account.currency,
        },
    }


def subscriptions_view(db: Session, user: User) -> dict[str, object]:
    streams = list(
        db.scalars(
            select(RecurringStream)
            .options(joinedload(RecurringStream.account))
            .where(RecurringStream.user_id == user.id, RecurringStream.active.is_(True))
            .order_by(RecurringStream.next_expected_date, RecurringStream.display_name)
        ).all()
    )
    subscriptions = [stream for stream in streams if is_subscription(stream)]
    active = [stream for stream in subscriptions if stream.subscription_status == "active"]
    monthly_total = sum((monthly_equivalent(stream.average_amount, stream.cadence) for stream in active), Decimal("0"))
    today = date.today()
    horizon = today + timedelta(days=30)
    upcoming = [
        stream
        for stream in active
        if today <= stream.next_expected_date <= horizon
    ]
    return {
        "currency": user.settings.currency,
        "active_count": len(active),
        "monthly_total": money(monthly_total),
        "annual_total": money(monthly_total * Decimal("12")),
        "upcoming_30_days": [_item(stream) for stream in upcoming],
        "subscriptions": [_item(stream) for stream in subscriptions],
    }


def update_subscription(
    db: Session,
    user: User,
    stream_id: int,
    *,
    is_subscription_value: bool | None,
    status: str | None,
) -> RecurringStream:
    stream = db.scalar(
        select(RecurringStream)
        .options(joinedload(RecurringStream.account))
        .where(RecurringStream.id == stream_id, RecurringStream.user_id == user.id)
        .with_for_update()
    )
    if stream is None:
        raise ApiError(404, "recurring_stream_not_found", "The recurring stream was not found")
    if is_subscription_value is not None:
        stream.subscription_override = is_subscription_value
        if is_subscription_value and stream.subscription_status == "cancelled":
            stream.subscription_status = "active"
    if status is not None:
        if status not in {"active", "paused", "cancelled"}:
            raise ApiError(422, "subscription_status_invalid", "Choose a valid subscription status")
        stream.subscription_status = status
        if status in {"active", "paused"} and stream.subscription_override is False:
            stream.subscription_override = True
    db.flush()
    return stream
