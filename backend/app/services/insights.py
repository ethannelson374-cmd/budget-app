from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import InsightRecord, User
from app.services.budget_planning import month_budget_view
from app.services.financial_planning import forecast_view, list_debts, list_goals
from app.services.transaction_intelligence import list_recurring_streams

Priority = Literal["critical", "important", "opportunity", "info"]
StatusFilter = Literal["active", "dismissed", "resolved", "all"]


@dataclass(frozen=True)
class Signal:
    fingerprint: str
    signal_type: str
    category: str
    priority: Priority
    score: int
    title: str
    summary: str
    recommendation: str | None
    evidence: list[dict[str, str | None]]
    action_route: str | None


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _fingerprint(signal_type: str, *parts: object) -> str:
    source = ":".join([signal_type, *(str(part) for part in parts)])
    return hashlib.sha256(source.encode()).hexdigest()


def _money(value: Decimal | object, currency: str) -> str:
    amount = _decimal(value)
    return f"{currency} {amount:,.2f}"


def _shift_month(month: str, delta: int) -> str:
    year, month_number = (int(value) for value in month.split("-"))
    absolute = year * 12 + month_number - 1 + delta
    next_year, month0 = divmod(absolute, 12)
    return f"{next_year:04d}-{month0 + 1:02d}"


def _budget_signals(db: Session, user: User, month: str) -> list[Signal]:
    currency = user.settings.currency
    current = cast(dict[str, Any], month_budget_view(db, user, month))
    signals: list[Signal] = []
    categories = cast(list[dict[str, Any]], current["categories"])

    previous_views = [
        cast(dict[str, Any], month_budget_view(db, user, _shift_month(month, offset)))
        for offset in (-1, -2, -3)
    ]
    previous_status: dict[int, int] = {}
    for view in previous_views:
        for row in cast(list[dict[str, Any]], view["categories"]):
            category = cast(dict[str, Any], row["category"])
            if row["status"] == "over":
                category_id = int(category["id"])
                previous_status[category_id] = previous_status.get(category_id, 0) + 1

    for row in categories:
        if row["status"] != "over":
            continue
        category = cast(dict[str, Any], row["category"])
        spent = _decimal(row["spent_amount"])
        available = _decimal(row["available_amount"])
        over = max(spent - available, Decimal("0"))
        pct_over = (over / available * Decimal("100")) if available > 0 else Decimal("100")
        repeats = previous_status.get(int(category["id"]), 0)
        score = 76
        priority: Priority = "important"
        if pct_over >= 25 or over >= Decimal("150") or repeats >= 2:
            score = 88
        if pct_over >= 50 and over >= Decimal("250"):
            priority = "critical"
            score = 94
        repeat_copy = (
            f" This category was also over budget in {repeats} of the prior 3 months."
            if repeats
            else ""
        )
        signals.append(
            Signal(
                fingerprint=_fingerprint("category_overspend", category["id"], month),
                signal_type="category_overspend",
                category="budget",
                priority=priority,
                score=score,
                title=f"{category['name']} spending is over budget",
                summary=(
                    f"You've spent {_money(spent, currency)} against "
                    f"{_money(available, currency)} available this month, "
                    f"or {_money(over, currency)} over plan.{repeat_copy}"
                ),
                recommendation=(
                    f"Hold additional {category['name'].lower()} spending to roughly "
                    f"{_money(max(available - spent, Decimal('0')), currency)} for the rest "
                    "of the month, or adjust the budget if the higher level is intentional."
                ),
                evidence=[
                    {"label": "Spent", "value": _money(spent, currency), "detail": month},
                    {
                        "label": "Available",
                        "value": _money(available, currency),
                        "detail": "Including rollover",
                    },
                    {
                        "label": "Over plan",
                        "value": _money(over, currency),
                        "detail": f"{pct_over:.1f}% above available budget",
                    },
                ],
                action_route="/budget",
            )
        )

    safe_to_spend = _decimal(current["safe_to_spend"])
    cash_available = _decimal(current["cash_available"])
    if safe_to_spend < 0:
        signals.append(
            Signal(
                fingerprint=_fingerprint("negative_safe_to_spend", month),
                signal_type="negative_safe_to_spend",
                category="cash_flow",
                priority="critical",
                score=98,
                title="Your safe-to-spend amount is below zero",
                summary=(
                    f"Budget currently calculates {_money(safe_to_spend, currency)} as safe "
                    "to spend after planned, recurring, goal, and debt commitments."
                ),
                recommendation=(
                    "Delay discretionary purchases, reduce flexible spending, or revisit "
                    "planning commitments until safe-to-spend is positive again."
                ),
                evidence=[
                    {
                        "label": "Safe to spend",
                        "value": _money(safe_to_spend, currency),
                        "detail": month,
                    },
                    {
                        "label": "Cash available",
                        "value": _money(cash_available, currency),
                        "detail": None,
                    },
                    {
                        "label": "Planning commitments",
                        "value": _money(current["planning_commitments"], currency),
                        "detail": "Goals and debt above budgeted reserves",
                    },
                ],
                action_route="/plan",
            )
        )
    elif cash_available > 0 and safe_to_spend / cash_available < Decimal("0.10"):
        signals.append(
            Signal(
                fingerprint=_fingerprint("low_safe_to_spend", month),
                signal_type="low_safe_to_spend",
                category="cash_flow",
                priority="important",
                score=82,
                title="Your spending cushion is getting thin",
                summary=(
                    f"Only {_money(safe_to_spend, currency)} is currently safe to spend, "
                    "less than 10% of available cash after protected commitments."
                ),
                recommendation=(
                    "Keep new discretionary spending modest until income lands or reserved "
                    "obligations clear."
                ),
                evidence=[
                    {
                        "label": "Safe to spend",
                        "value": _money(safe_to_spend, currency),
                        "detail": month,
                    },
                    {
                        "label": "Cash available",
                        "value": _money(cash_available, currency),
                        "detail": None,
                    },
                ],
                action_route="/budget",
            )
        )
    return signals


def _recurring_signals(db: Session, user: User) -> list[Signal]:
    currency = user.settings.currency
    streams = list_recurring_streams(db, user)
    signals: list[Signal] = []
    factors = {
        "weekly": Decimal("52") / Decimal("12"),
        "biweekly": Decimal("26") / Decimal("12"),
        "monthly": Decimal("1"),
        "quarterly": Decimal("1") / Decimal("3"),
        "annual": Decimal("1") / Decimal("12"),
    }
    monthly_outflow = Decimal("0")
    for stream in streams:
        if stream.kind != "expense":
            continue
        monthly_outflow += stream.average_amount * factors.get(stream.cadence, Decimal("0"))
        change = stream.price_change_pct
        if change is None or change < Decimal("10"):
            continue
        increase = max(stream.last_amount - stream.average_amount, Decimal("0"))
        priority: Priority = "important" if change >= Decimal("20") else "opportunity"
        signals.append(
            Signal(
                fingerprint=_fingerprint(
                    "recurring_price_increase", stream.account_id, stream.merchant_key
                ),
                signal_type="recurring_price_increase",
                category="recurring",
                priority=priority,
                score=78 if priority == "important" else 62,
                title=f"{stream.display_name} appears to have increased",
                summary=(
                    f"The latest recurring charge is {_money(stream.last_amount, currency)}, "
                    f"about {change:.1f}% above its prior pattern."
                ),
                recommendation=(
                    "Review the charge to confirm the increase is expected and still worth "
                    "keeping at the new price."
                ),
                evidence=[
                    {
                        "label": "Latest charge",
                        "value": _money(stream.last_amount, currency),
                        "detail": stream.last_date.isoformat(),
                    },
                    {
                        "label": "Detected average",
                        "value": _money(stream.average_amount, currency),
                        "detail": stream.cadence,
                    },
                    {
                        "label": "Change",
                        "value": f"+{change:.1f}%",
                        "detail": _money(increase, currency) if increase > 0 else None,
                    },
                ],
                action_route="/recurring",
            )
        )

    if monthly_outflow >= Decimal("50"):
        annualized = monthly_outflow * Decimal("12")
        signals.append(
            Signal(
                fingerprint=_fingerprint("recurring_annualized_total"),
                signal_type="recurring_annualized_total",
                category="recurring",
                priority="info",
                score=34,
                title="Your recurring expenses add up over a year",
                summary=(
                    f"Detected recurring expenses are about {_money(monthly_outflow, currency)} "
                    f"per month, or roughly {_money(annualized, currency)} per year."
                ),
                recommendation=(
                    "Use the Recurring page to review the biggest repeating charges and decide "
                    "whether each one still earns its place in the budget."
                ),
                evidence=[
                    {
                        "label": "Monthly estimate",
                        "value": _money(monthly_outflow, currency),
                        "detail": "Cadence-normalized",
                    },
                    {
                        "label": "Annualized",
                        "value": _money(annualized, currency),
                        "detail": "Monthly estimate × 12",
                    },
                ],
                action_route="/recurring",
            )
        )
    return signals


def _planning_signals(db: Session, user: User) -> list[Signal]:
    currency = user.settings.currency
    today = _today(user)
    signals: list[Signal] = []
    goals = cast(dict[str, Any], list_goals(db, user))
    for goal in cast(list[dict[str, Any]], goals["goals"]):
        if not goal["active"] or goal["target_date"] is None:
            continue
        target_date = cast(date, goal["target_date"])
        projected_date = cast(date | None, goal["projected_date"])
        if projected_date is not None and projected_date <= target_date:
            continue
        remaining = _decimal(goal["remaining_amount"])
        months_left = max(
            (target_date.year - today.year) * 12 + target_date.month - today.month, 1
        )
        required = remaining / Decimal(months_left)
        current = _decimal(goal["monthly_contribution"])
        shortfall = max(required - current, Decimal("0"))
        days_left = (target_date - today).days
        priority: Priority = "critical" if days_left <= 90 else "important"
        score = 92 if priority == "critical" else 79
        projected_copy = (
            f"Current contributions project completion around {projected_date.isoformat()}."
            if projected_date is not None
            else "At the current contribution rate, Budget cannot project completion."
        )
        signals.append(
            Signal(
                fingerprint=_fingerprint("goal_behind_schedule", goal["id"]),
                signal_type="goal_behind_schedule",
                category="goal",
                priority=priority,
                score=score,
                title=f"{goal['name']} is behind its target pace",
                summary=(
                    f"The target date is {target_date.isoformat()}. {projected_copy}"
                ),
                recommendation=(
                    f"A contribution near {_money(required, currency)} per month would match the "
                    f"remaining timeline, about {_money(shortfall, currency)} above the current "
                    "monthly contribution."
                ),
                evidence=[
                    {
                        "label": "Remaining",
                        "value": _money(remaining, currency),
                        "detail": None,
                    },
                    {
                        "label": "Current monthly",
                        "value": _money(current, currency),
                        "detail": None,
                    },
                    {
                        "label": "Needed monthly",
                        "value": _money(required, currency),
                        "detail": f"Approximate pace for {target_date.isoformat()}",
                    },
                ],
                action_route="/plan",
            )
        )

    debts = cast(dict[str, Any], list_debts(db, user))
    high_interest = [
        debt
        for debt in cast(list[dict[str, Any]], debts["debts"])
        if debt["active"]
        and _decimal(debt["balance"]) >= Decimal("250")
        and _decimal(debt["apr"]) >= Decimal("15")
    ]
    for debt in high_interest:
        apr = _decimal(debt["apr"])
        balance = _decimal(debt["balance"])
        saved = _decimal(debt["interest_saved"])
        signals.append(
            Signal(
                fingerprint=_fingerprint("high_interest_debt", debt["id"]),
                signal_type="high_interest_debt",
                category="debt",
                priority="opportunity",
                score=min(74, 52 + int(apr)),
                title=f"{debt['name']} is expensive debt",
                summary=(
                    f"This balance is {_money(balance, currency)} at {apr:.2f}% APR. Higher-rate "
                    "debt is usually the strongest mathematical payoff target after required "
                    "reserves and minimums are protected."
                ),
                recommendation=(
                    "Consider directing available extra debt budget toward this balance under "
                    "the avalanche strategy."
                ),
                evidence=[
                    {"label": "Balance", "value": _money(balance, currency), "detail": None},
                    {"label": "APR", "value": f"{apr:.2f}%", "detail": None},
                    {
                        "label": "Plan interest saved",
                        "value": _money(saved, currency),
                        "detail": "Compared with minimum-only simulation",
                    },
                ],
                action_route="/plan",
            )
        )

    forecast = cast(dict[str, Any], forecast_view(db, user))
    risky = [
        row
        for row in cast(list[dict[str, Any]], forecast["horizons"])
        if _decimal(row["above_reserve"]) < 0
    ]
    if risky:
        earliest = min(risky, key=lambda row: int(row["days"]))
        days = int(earliest["days"])
        shortfall = abs(_decimal(earliest["above_reserve"]))
        projected = _decimal(earliest["projected_balance"])
        reserve = _decimal(forecast["reserve_balance"])
        priority: Priority = "critical" if days <= 30 else "important"
        signals.append(
            Signal(
                fingerprint=_fingerprint("forecast_reserve_risk", days),
                signal_type="forecast_reserve_risk",
                category="forecast",
                priority=priority,
                score=96 if priority == "critical" else 86,
                title=f"Your {days}-day forecast falls below your reserve",
                summary=(
                    f"Projected cash is {_money(projected, currency)}, about "
                    f"{_money(shortfall, currency)} below the protected reserve by the "
                    f"{days}-day horizon."
                ),
                recommendation=(
                    "Use the forecast scenario tool to test a spending reduction, lower goal "
                    "contribution, or delayed extra debt payment before the shortfall arrives."
                ),
                evidence=[
                    {
                        "label": "Projected balance",
                        "value": _money(projected, currency),
                        "detail": f"{days}-day horizon",
                    },
                    {
                        "label": "Protected reserve",
                        "value": _money(reserve, currency),
                        "detail": None,
                    },
                    {
                        "label": "Below reserve",
                        "value": _money(shortfall, currency),
                        "detail": None,
                    },
                ],
                action_route="/plan",
            )
        )
    return signals


def generate_signals(db: Session, user: User) -> list[Signal]:
    month = _today(user).strftime("%Y-%m")
    signals = [
        *_budget_signals(db, user, month),
        *_recurring_signals(db, user),
        *_planning_signals(db, user),
    ]
    deduped = {signal.fingerprint: signal for signal in signals}
    return sorted(deduped.values(), key=lambda item: (-item.score, item.title.casefold()))


def refresh_insights(db: Session, user: User) -> None:
    # Serialize refreshes for one owner so multiple browser tabs cannot race the
    # unique (user_id, fingerprint) constraint while creating the same signal.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    now = utc_now()
    signals = generate_signals(db, user)
    existing = list(
        db.scalars(select(InsightRecord).where(InsightRecord.user_id == user.id)).all()
    )
    by_fingerprint = {row.fingerprint: row for row in existing}
    seen: set[str] = set()

    for signal in signals:
        seen.add(signal.fingerprint)
        row = by_fingerprint.get(signal.fingerprint)
        if row is None:
            row = InsightRecord(
                user_id=user.id,
                fingerprint=signal.fingerprint,
                signal_type=signal.signal_type,
                category=signal.category,
                priority=signal.priority,
                score=signal.score,
                status="active",
                title=signal.title,
                summary=signal.summary,
                recommendation=signal.recommendation,
                evidence_json=json.dumps(signal.evidence, separators=(",", ":")),
                action_route=signal.action_route,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            continue
        row.signal_type = signal.signal_type
        row.category = signal.category
        row.priority = signal.priority
        row.score = signal.score
        row.title = signal.title
        row.summary = signal.summary
        row.recommendation = signal.recommendation
        row.evidence_json = json.dumps(signal.evidence, separators=(",", ":"))
        row.action_route = signal.action_route
        row.last_seen_at = now
        if row.status == "resolved":
            row.status = "active"
            row.resolved_at = None
            row.dismissed_at = None

    for row in existing:
        if row.fingerprint in seen or row.status == "resolved":
            continue
        row.status = "resolved"
        row.resolved_at = now

    db.flush()


def _evidence(row: InsightRecord) -> list[dict[str, str | None]]:
    try:
        value = json.loads(row.evidence_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    result: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        value_text = item.get("value")
        detail = item.get("detail")
        if isinstance(label, str) and isinstance(value_text, str):
            result.append(
                {
                    "label": label,
                    "value": value_text,
                    "detail": detail if isinstance(detail, str) else None,
                }
            )
    return result


def insight_view(row: InsightRecord) -> dict[str, object]:
    return {
        "id": row.id,
        "signal_type": row.signal_type,
        "category": row.category,
        "priority": row.priority,
        "score": row.score,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "recommendation": row.recommendation,
        "evidence": _evidence(row),
        "action_route": row.action_route,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "dismissed_at": row.dismissed_at,
        "resolved_at": row.resolved_at,
    }


def list_insights(
    db: Session, user: User, *, status: StatusFilter = "active"
) -> dict[str, object]:
    rows = list(
        db.scalars(
            select(InsightRecord)
            .where(InsightRecord.user_id == user.id)
            .order_by(InsightRecord.score.desc(), InsightRecord.last_seen_at.desc())
        ).all()
    )
    counts = {
        "active": sum(row.status == "active" for row in rows),
        "dismissed": sum(row.status == "dismissed" for row in rows),
        "resolved": sum(row.status == "resolved" for row in rows),
    }
    visible = rows if status == "all" else [row for row in rows if row.status == status]
    return {
        "generated_at": utc_now(),
        "active_count": counts["active"],
        "dismissed_count": counts["dismissed"],
        "resolved_count": counts["resolved"],
        "insights": [insight_view(row) for row in visible],
    }


def set_insight_status(
    db: Session, user: User, insight_id: int, status: Literal["active", "dismissed"]
) -> InsightRecord:
    row = db.scalar(
        select(InsightRecord).where(
            InsightRecord.id == insight_id, InsightRecord.user_id == user.id
        )
    )
    if row is None:
        raise ApiError(404, "insight_not_found", "The insight was not found")
    if row.status == "resolved" and status == "active":
        raise ApiError(409, "insight_resolved", "Resolved insights cannot be restored")
    row.status = status
    if status == "dismissed":
        row.dismissed_at = utc_now()
    else:
        row.dismissed_at = None
    db.flush()
    return row
