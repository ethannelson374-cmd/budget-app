from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import (
    Account,
    FinancialGoal,
    InsightRecord,
    Notification,
    PlaidItem,
    Transaction,
    User,
    UserNotificationPreference,
)
from app.services.email_delivery import EmailDeliveryError, send_email
from app.services.insights import refresh_insights
from app.services.transaction_intelligence import effective_kind, effective_merchant

NotificationFilter = Literal["all", "unread"]
MILESTONES = (25, 50, 75, 100)


def _local_now(user: User) -> datetime:
    return datetime.now(ZoneInfo(user.settings.timezone))


def _money(value: Decimal, currency: str) -> str:
    return f"{currency} {value.copy_abs():,.2f}"


def get_preferences(
    db: Session, user: User, *, persist: bool = False
) -> UserNotificationPreference:
    row = db.get(UserNotificationPreference, user.id)
    if row is None:
        row = UserNotificationPreference(
            user_id=user.id,
            in_app_enabled=True,
            email_enabled=False,
            spending_alerts=True,
            forecast_alerts=True,
            goal_milestones=True,
            recurring_changes=True,
            large_transaction_alerts=False,
            large_transaction_threshold=Decimal("250.0000"),
            weekly_summary=True,
            monthly_summary=True,
        )
        if persist:
            db.add(row)
            db.flush()
    return row


def preferences_view(row: UserNotificationPreference, settings: Settings) -> dict[str, object]:
    return {
        "in_app_enabled": row.in_app_enabled,
        "email_enabled": row.email_enabled,
        "email_delivery_available": settings.email_configured,
        "spending_alerts": row.spending_alerts,
        "forecast_alerts": row.forecast_alerts,
        "goal_milestones": row.goal_milestones,
        "recurring_changes": row.recurring_changes,
        "large_transaction_alerts": row.large_transaction_alerts,
        "large_transaction_threshold": format(row.large_transaction_threshold, "f"),
        "weekly_summary": row.weekly_summary,
        "monthly_summary": row.monthly_summary,
    }


def update_preferences(
    db: Session, user: User, payload: dict[str, object], settings: Settings
) -> dict[str, object]:
    row = get_preferences(db, user, persist=True)
    for key, value in payload.items():
        if value is not None:
            setattr(row, key, value)
    db.flush()
    return preferences_view(row, settings)


def notification_view(row: Notification) -> dict[str, object]:
    try:
        data = json.loads(row.data_json)
        if not isinstance(data, dict):
            data = {}
    except json.JSONDecodeError:
        data = {}
    return {
        "id": row.id,
        "type": row.notification_type,
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "action_route": row.action_route,
        "data": data,
        "occurred_at": row.occurred_at,
        "read_at": row.read_at,
        "dismissed_at": row.dismissed_at,
        "email_sent_at": row.email_sent_at,
    }


def list_notifications(
    db: Session, user: User, *, status: NotificationFilter = "all", limit: int = 50
) -> dict[str, object]:
    prefs = get_preferences(db, user)
    if not prefs.in_app_enabled:
        return {"unread_count": 0, "notifications": []}
    clauses = [Notification.user_id == user.id, Notification.dismissed_at.is_(None)]
    if status == "unread":
        clauses.append(Notification.read_at.is_(None))
    rows = list(
        db.scalars(
            select(Notification)
            .where(*clauses)
            .order_by(Notification.occurred_at.desc(), Notification.id.desc())
            .limit(limit)
        ).all()
    )
    unread = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.dismissed_at.is_(None),
                Notification.read_at.is_(None),
            )
        )
        or 0
    )
    return {"unread_count": unread, "notifications": [notification_view(row) for row in rows]}


def unread_count(db: Session, user: User) -> int:
    prefs = get_preferences(db, user)
    if not prefs.in_app_enabled:
        return 0
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.dismissed_at.is_(None),
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def mark_notification(
    db: Session,
    user: User,
    notification_id: int,
    *,
    read: bool | None = None,
    dismissed: bool | None = None,
) -> Notification:
    row = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if row is None:
        raise ApiError(404, "notification_not_found", "The notification was not found")
    now = utc_now()
    if read is not None:
        row.read_at = now if read else None
    if dismissed is not None:
        row.dismissed_at = now if dismissed else None
        if dismissed and row.read_at is None:
            row.read_at = now
    db.flush()
    return row


def mark_all_read(db: Session, user: User) -> int:
    rows = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.dismissed_at.is_(None),
                Notification.read_at.is_(None),
            )
        ).all()
    )
    now = utc_now()
    for row in rows:
        row.read_at = now
    db.flush()
    return len(rows)


def _create(
    db: Session,
    user: User,
    *,
    fingerprint: str,
    notification_type: str,
    severity: str,
    title: str,
    body: str,
    action_route: str | None,
    data: dict[str, Any] | None = None,
) -> Notification | None:
    if db.scalar(
        select(Notification.id).where(
            Notification.user_id == user.id, Notification.fingerprint == fingerprint
        )
    ) is not None:
        return None
    row = Notification(
        user_id=user.id,
        fingerprint=fingerprint[:128],
        notification_type=notification_type[:48],
        severity=severity,
        title=title[:180],
        body=body,
        action_route=action_route,
        data_json=json.dumps(data or {}, separators=(",", ":"), default=str),
        occurred_at=utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def _insight_notifications(
    db: Session, user: User, prefs: UserNotificationPreference
) -> list[Notification]:
    refresh_insights(db, user)
    rows = list(
        db.scalars(
            select(InsightRecord).where(
                InsightRecord.user_id == user.id, InsightRecord.status == "active"
            )
        ).all()
    )
    created: list[Notification] = []
    for insight in rows:
        enabled = False
        if insight.signal_type in {"category_overspend", "negative_safe_to_spend", "low_safe_to_spend"}:
            enabled = prefs.spending_alerts
        elif insight.signal_type == "forecast_reserve_risk":
            enabled = prefs.forecast_alerts
        elif insight.signal_type == "recurring_price_increase":
            enabled = prefs.recurring_changes
        if not enabled:
            continue
        if insight.priority not in {"critical", "important", "opportunity"}:
            continue
        row = _create(
            db,
            user,
            fingerprint=f"insight:{insight.fingerprint}",
            notification_type=insight.signal_type,
            severity=insight.priority,
            title=insight.title,
            body=insight.summary,
            action_route=insight.action_route,
            data={"insight_id": insight.id},
        )
        if row is not None:
            created.append(row)
    return created


def _goal_notifications(
    db: Session, user: User, prefs: UserNotificationPreference
) -> list[Notification]:
    if not prefs.goal_milestones:
        return []
    goals = list(
        db.scalars(
            select(FinancialGoal).where(
                FinancialGoal.user_id == user.id, FinancialGoal.active.is_(True)
            )
        ).all()
    )
    created: list[Notification] = []
    for goal in goals:
        if goal.target_amount <= 0:
            continue
        pct = int((goal.current_amount / goal.target_amount * Decimal("100")).to_integral_value())
        reached = [value for value in MILESTONES if pct >= value]
        if not reached:
            continue
        milestone = max(reached)
        row = _create(
            db,
            user,
            fingerprint=f"goal:{goal.id}:milestone:{milestone}",
            notification_type="goal_milestone",
            severity="opportunity" if milestone < 100 else "important",
            title=(f"{goal.name} reached {milestone}%" if milestone < 100 else f"{goal.name} is fully funded"),
            body=(
                f"You've saved {_money(goal.current_amount, user.settings.currency)} toward "
                f"your {_money(goal.target_amount, user.settings.currency)} target."
            ),
            action_route="/plan",
            data={"goal_id": goal.id, "milestone": milestone},
        )
        if row is not None:
            created.append(row)
    return created


def _plaid_connection_notifications(
    db: Session, settings: Settings, user: User
) -> list[Notification]:
    items = list(
        db.scalars(
            select(PlaidItem)
            .options(joinedload(PlaidItem.institution))
            .where(PlaidItem.user_id == user.id)
            .order_by(PlaidItem.id)
        ).all()
    )
    created: list[Notification] = []
    for item in items:
        reason = item.update_reason or item.last_error_code
        if item.environment != settings.plaid_env:
            reason = "ENVIRONMENT_MISMATCH"
        if not reason and item.status != "error":
            continue
        institution = item.institution.name if item.institution else "Bank connection"
        if reason == "NEW_ACCOUNTS_AVAILABLE":
            title = f"New accounts available at {institution}"
            body = "Your bank reports additional accounts that can be shared with Budget. Review the connection to choose them."
            severity = "info"
        elif reason in {"PENDING_DISCONNECT", "PENDING_EXPIRATION"}:
            title = f"Renew access to {institution}"
            body = "Your bank authorization is nearing expiration. Reconnect now to keep transaction updates working."
            severity = "important"
        elif reason == "ENVIRONMENT_MISMATCH":
            title = f"Replace the test connection for {institution}"
            body = "This Plaid Sandbox connection cannot move into Production. Remove it and connect the real institution again."
            severity = "important"
        else:
            title = f"Reconnect {institution}"
            body = "Budget can no longer refresh this bank connection automatically. Open Accounts and reconnect it through Plaid."
            severity = "important"
        stamp = item.last_webhook_at or item.updated_at or item.created_at
        bucket = stamp.strftime("%Y-%m-%d") if stamp else "current"
        row = _create(
            db,
            user,
            fingerprint=f"plaid:{item.id}:{reason}:{bucket}",
            notification_type="bank_connection",
            severity=severity,
            title=title,
            body=body,
            action_route="/accounts",
            data={"connection_id": item.id, "reason": reason},
        )
        if row is not None:
            created.append(row)
    return created


def _large_transaction_notifications(
    db: Session, user: User, prefs: UserNotificationPreference
) -> list[Notification]:
    if not prefs.large_transaction_alerts:
        return []
    since = utc_now() - timedelta(hours=48)
    rows = list(
        db.scalars(
            select(Transaction)
            .options(joinedload(Transaction.account))
            .where(
                Transaction.user_id == user.id,
                Transaction.imported_at >= since,
                Transaction.pending.is_(False),
            )
            .order_by(Transaction.imported_at.desc())
        ).all()
    )
    created: list[Notification] = []
    for transaction in rows:
        if transaction.account.currency != user.settings.currency:
            continue
        if effective_kind(transaction) != "expense":
            continue
        amount = transaction.amount.copy_abs()
        if amount < prefs.large_transaction_threshold:
            continue
        merchant = effective_merchant(transaction) or transaction.description or "Transaction"
        row = _create(
            db,
            user,
            fingerprint=f"large_transaction:{transaction.id}",
            notification_type="large_transaction",
            severity="important",
            title=f"Large transaction: {merchant}",
            body=f"A {_money(amount, user.settings.currency)} expense posted on {transaction.posted_date.isoformat()}.",
            action_route="/transactions",
            data={"transaction_id": transaction.id, "amount": format(amount, "f")},
        )
        if row is not None:
            created.append(row)
    return created


def _period_totals(db: Session, user: User, start: date, end: date) -> tuple[Decimal, Decimal]:
    account_ids = list(
        db.scalars(
            select(Account.id).where(
                Account.user_id == user.id, Account.currency == user.settings.currency
            )
        ).all()
    )
    if not account_ids:
        return Decimal("0"), Decimal("0")
    rows = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.account_id.in_(account_ids),
                Transaction.posted_date >= start,
                Transaction.posted_date <= end,
                Transaction.excluded_from_spending.is_(False),
            )
        ).all()
    )
    income = Decimal("0")
    spending = Decimal("0")
    for transaction in rows:
        kind = effective_kind(transaction)
        if kind == "income":
            income += transaction.amount
        elif kind == "expense":
            spending += transaction.amount.copy_abs()
        elif kind == "refund":
            spending -= transaction.amount
    return max(income, Decimal("0")), max(spending, Decimal("0"))


def _summary_notification(
    db: Session,
    user: User,
    *,
    kind: Literal["weekly", "monthly"],
    force: bool,
) -> Notification | None:
    local = _local_now(user)
    today = local.date()
    if kind == "weekly":
        if not force and today.weekday() != 0:
            return None
        end = today - timedelta(days=1)
        start = end - timedelta(days=6)
        period = f"{start.isoformat()}:{end.isoformat()}"
        title = "Your weekly Budget summary"
    else:
        if not force and today.day != 1:
            return None
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
        period = start.strftime("%Y-%m")
        title = f"Your {start.strftime('%B')} Budget summary"
    income, spending = _period_totals(db, user, start, end)
    net = income - spending
    active_insights = int(
        db.scalar(
            select(func.count(InsightRecord.id)).where(
                InsightRecord.user_id == user.id, InsightRecord.status == "active"
            )
        )
        or 0
    )
    net_label = f"{user.settings.currency} {net:+,.2f}"
    body = (
        f"{start.strftime('%b %d')}–{end.strftime('%b %d')}: "
        f"{_money(income, user.settings.currency)} income, "
        f"{_money(spending, user.settings.currency)} spending, "
        f"net {net_label}. "
        f"You have {active_insights} active financial insight{'s' if active_insights != 1 else ''}."
    )
    return _create(
        db,
        user,
        fingerprint=f"{kind}_summary:{period}",
        notification_type=f"{kind}_summary",
        severity="info",
        title=title,
        body=body,
        action_route="/reports",
        data={"start": start.isoformat(), "end": end.isoformat()},
    )


def _deliver_email(settings: Settings, user: User, row: Notification) -> None:
    if not settings.email_configured:
        return
    route = row.action_route or "/notifications"
    base = (settings.public_app_url or "").rstrip("/")
    link = f"{base}{route}" if base else route
    text = f"{row.body}\n\nOpen Budget: {link}\n"
    try:
        send_email(settings, to_email=user.email, subject=f"Budget: {row.title}", text=text)
        row.email_sent_at = utc_now()
        row.email_error = None
    except EmailDeliveryError as exc:
        row.email_error = type(exc).__name__[:160]


def scan_user_notifications(
    db: Session, settings: Settings, user: User, *, force_summaries: bool = False
) -> dict[str, int]:
    prefs = get_preferences(db, user, persist=True)
    created: list[Notification] = []
    if prefs.in_app_enabled or prefs.email_enabled:
        created.extend(_insight_notifications(db, user, prefs))
        created.extend(_goal_notifications(db, user, prefs))
        created.extend(_plaid_connection_notifications(db, settings, user))
        created.extend(_large_transaction_notifications(db, user, prefs))
        if prefs.weekly_summary:
            row = _summary_notification(db, user, kind="weekly", force=force_summaries)
            if row is not None:
                created.append(row)
        if prefs.monthly_summary:
            row = _summary_notification(db, user, kind="monthly", force=force_summaries)
            if row is not None:
                created.append(row)
    db.commit()
    emailed = 0
    if prefs.email_enabled:
        for row in created:
            _deliver_email(settings, user, row)
            if row.email_sent_at is not None:
                emailed += 1
        db.commit()
    return {"created": len(created), "emailed": emailed}


def scan_all_notifications(
    db: Session, settings: Settings, *, force_summaries: bool = False
) -> dict[str, int]:
    users = list(
        db.scalars(select(User).options(selectinload(User.settings)).order_by(User.id)).all()
    )
    succeeded = 0
    failed = 0
    created = 0
    emailed = 0
    for user in users:
        try:
            result = scan_user_notifications(
                db, settings, user, force_summaries=force_summaries
            )
            succeeded += 1
            created += result["created"]
            emailed += result["emailed"]
        except Exception:
            db.rollback()
            failed += 1
    return {
        "succeeded": succeeded,
        "failed": failed,
        "created": created,
        "emailed": emailed,
    }
