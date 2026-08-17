from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import (
    Account,
    AccountBalanceSnapshot,
    AnnualBudgetCategory,
    AnnualBudgetMonthAllocation,
    AnnualBudgetPlan,
    AdvisorConversation,
    AdvisorMessage,
    AdvisorProposal,
    AdvisorProposalAction,
    AdvisorProposalExecution,
    Category,
    Debt,
    DebtStrategySettings,
    FinancialGoal,
    FinancialInstitution,
    FinancialSnapshot,
    ForecastAssumptions,
    GoalContribution,
    InsightRecord,
    MonthlyBudget,
    MonthlyBudgetCategory,
    Notification,
    PlaidItem,
    RecurringStream,
    SavedReport,
    Transaction,
    TransactionRule,
    User,
    UserDashboardPreference,
    UserNotificationPreference,
)
from app.services.manual_finance import owned_account, validate_transaction_sign
from app.services.views import money, settings_view

CSV_TEMPLATE = "date,description,amount,merchant,category,kind,notes,external_id\n2026-08-15,Example grocery purchase,-42.19,Example Market,groceries,expense,Optional note,\n"
MAX_IMPORT_ROWS = 5_000
_ALLOWED_KINDS = {"income", "expense", "transfer", "refund"}


def _json_value(value: object) -> object:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes omitted>"
    return value


def _serialize(row: object, *, exclude: set[str] | None = None) -> dict[str, object]:
    excluded = exclude or set()
    table = row.__class__.__table__
    return {
        column.name: _json_value(getattr(row, column.name))
        for column in table.columns
        if column.name not in excluded
    }


def _rows(db: Session, model: type[Any], user_id: int, *, exclude: set[str] | None = None) -> list[dict[str, object]]:
    return [
        _serialize(row, exclude=exclude)
        for row in db.scalars(select(model).where(model.user_id == user_id)).all()
    ]


def export_user_bundle(db: Session, user: User) -> dict[str, object]:
    """Return a secret-free, portable JSON representation of a user's Budget data."""
    uid = user.id
    data: dict[str, object] = {
        "dashboard_preferences": _rows(db, UserDashboardPreference, uid),
        "notification_preferences": _rows(db, UserNotificationPreference, uid),
        "notifications": _rows(db, Notification, uid),
        "financial_institutions": _rows(db, FinancialInstitution, uid, exclude={"logo_base64"}),
        "plaid_connections": _rows(
            db,
            PlaidItem,
            uid,
            exclude={"access_token_ciphertext", "access_token_nonce", "transactions_cursor"},
        ),
        "accounts": _rows(db, Account, uid),
        "account_balance_snapshots": _rows(db, AccountBalanceSnapshot, uid),
        "categories": _rows(db, Category, uid),
        "transactions": _rows(db, Transaction, uid),
        "transaction_rules": _rows(db, TransactionRule, uid),
        "recurring_streams": _rows(db, RecurringStream, uid),
        "annual_budget_plans": _rows(db, AnnualBudgetPlan, uid),
        "annual_budget_categories": _rows(db, AnnualBudgetCategory, uid),
        "annual_budget_month_allocations": [
            _serialize(row)
            for row in db.scalars(
                select(AnnualBudgetMonthAllocation).where(
                    AnnualBudgetMonthAllocation.annual_category_id.in_(
                        select(AnnualBudgetCategory.id).where(AnnualBudgetCategory.user_id == uid)
                    )
                )
            ).all()
        ],
        "monthly_budgets": _rows(db, MonthlyBudget, uid),
        "monthly_budget_categories": _rows(db, MonthlyBudgetCategory, uid),
        "goals": _rows(db, FinancialGoal, uid),
        "goal_contributions": _rows(db, GoalContribution, uid),
        "debts": _rows(db, Debt, uid),
        "debt_strategy": _rows(db, DebtStrategySettings, uid),
        "forecast_assumptions": _rows(db, ForecastAssumptions, uid),
        "financial_snapshots": _rows(db, FinancialSnapshot, uid),
        "saved_reports": _rows(db, SavedReport, uid),
        "insights": _rows(db, InsightRecord, uid),
        "advisor_conversations": _rows(db, AdvisorConversation, uid),
        "advisor_messages": _rows(db, AdvisorMessage, uid),
        "advisor_proposals": _rows(db, AdvisorProposal, uid),
        "advisor_proposal_actions": _rows(db, AdvisorProposalAction, uid),
        "advisor_proposal_executions": _rows(db, AdvisorProposalExecution, uid),
    }
    return {
        "format": "budget-user-export",
        "version": 1,
        "generated_at": utc_now().isoformat(),
        "profile": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "email_verified": user.email_verified_at is not None,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
            "settings": settings_view(user.settings),
        },
        "security_note": "Passwords, session tokens, 2FA secrets, Plaid access tokens, OAuth state, and recovery codes are intentionally excluded.",
        "data": data,
    }


def export_transactions_csv(db: Session, user: User) -> str:
    rows = list(
        db.scalars(
            select(Transaction)
            .options(joinedload(Transaction.account), joinedload(Transaction.category))
            .where(Transaction.user_id == user.id)
            .order_by(Transaction.posted_date.asc(), Transaction.id.asc())
        ).all()
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "account",
            "description",
            "merchant",
            "amount",
            "kind",
            "category",
            "pending",
            "source",
            "notes",
        ]
    )
    for tx in rows:
        writer.writerow(
            [
                tx.posted_date.isoformat(),
                tx.account.name,
                tx.description,
                tx.display_merchant or tx.merchant or "",
                money(tx.amount),
                tx.user_kind_override or tx.kind,
                tx.category.name if tx.category else "",
                "true" if tx.pending else "false",
                tx.source_type,
                tx.notes or "",
            ]
        )
    return output.getvalue()


def _clean(value: object, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise ValueError(f"value exceeds {limit} characters")
    return text


def _category_maps(db: Session, user: User) -> tuple[dict[str, Category], dict[str, Category]]:
    categories = list(db.scalars(select(Category).where(Category.user_id == user.id)).all())
    by_key = {row.stable_key.casefold(): row for row in categories}
    by_name = {row.name.casefold(): row for row in categories}
    return by_key, by_name


def _fingerprint(account_id: int, row: dict[str, str], *, posted: date, description: str, amount: Decimal, kind: str, merchant: str | None) -> str:
    provider_id = str(row.get("external_id") or "").strip()
    material = "|".join(
        [
            str(account_id),
            provider_id,
            posted.isoformat(),
            description,
            format(amount, "f"),
            kind,
            merchant or "",
        ]
    )
    return "csv:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def import_transactions_csv(db: Session, user: User, *, account_id: int, csv_text: str) -> dict[str, object]:
    account = owned_account(db, user, account_id)
    if account.source_type != "manual":
        raise ApiError(
            409,
            "csv_import_requires_manual_account",
            "Import CSV history into a manual account so provider-managed transactions cannot be duplicated",
        )
    if len(csv_text.encode("utf-8")) > 2_000_000:
        raise ApiError(413, "csv_too_large", "CSV imports are limited to 2 MB")

    text = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    headers = {str(name or "").strip().casefold() for name in (reader.fieldnames or [])}
    required = {"date", "description", "amount"}
    if not required.issubset(headers):
        raise ApiError(422, "csv_headers_invalid", "CSV must include date, description, and amount columns")

    key_map, name_map = _category_maps(db, user)
    prepared: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    seen: set[str] = set()
    skipped = 0
    total = 0

    for row_number, raw in enumerate(reader, start=2):
        total += 1
        if total > MAX_IMPORT_ROWS:
            raise ApiError(422, "csv_too_many_rows", f"CSV imports are limited to {MAX_IMPORT_ROWS} rows")
        row = {str(k or "").strip().casefold(): str(v or "").strip() for k, v in raw.items()}
        try:
            posted = date.fromisoformat(row.get("date", ""))
            description = _clean(row.get("description"), 255)
            if not description:
                raise ValueError("description is required")
            try:
                amount = Decimal(row.get("amount", ""))
            except (InvalidOperation, ValueError):
                raise ValueError("amount must be a number") from None
            if not amount.is_finite() or abs(amount) >= Decimal("1000000000000000"):
                raise ValueError("amount is outside the supported range")
            kind = row.get("kind", "").casefold() or ("expense" if amount < 0 else "income")
            if kind not in _ALLOWED_KINDS:
                raise ValueError("kind must be income, expense, transfer, or refund")
            validate_transaction_sign(kind, amount)
            merchant = _clean(row.get("merchant"), 160)
            notes = _clean(row.get("notes"), 4000)
            category: Category | None = None
            category_text = row.get("category", "").strip().casefold()
            if category_text:
                category = key_map.get(category_text) or name_map.get(category_text)
                if category is None:
                    raise ValueError(f"unknown category '{row.get('category', '')}'")
            fingerprint = _fingerprint(
                account.id,
                row,
                posted=posted,
                description=description,
                amount=amount,
                kind=kind,
                merchant=merchant,
            )
            if fingerprint in seen:
                skipped += 1
                continue
            seen.add(fingerprint)
            prepared.append(
                {
                    "fingerprint": fingerprint,
                    "posted_date": posted,
                    "description": description,
                    "merchant": merchant,
                    "amount": amount,
                    "kind": kind,
                    "notes": notes,
                    "category": category,
                }
            )
        except (ValueError, ApiError) as exc:
            message = exc.message if isinstance(exc, ApiError) else str(exc)
            if len(errors) < 50:
                errors.append({"row": row_number, "message": message})

    if total == 0:
        raise ApiError(422, "csv_empty", "CSV does not contain any transaction rows")

    fingerprints = [str(item["fingerprint"]) for item in prepared]
    existing: set[str] = set()
    for start in range(0, len(fingerprints), 500):
        batch = fingerprints[start : start + 500]
        if batch:
            existing.update(
                str(value)
                for value in db.scalars(
                    select(Transaction.external_id).where(
                        Transaction.user_id == user.id,
                        Transaction.account_id == account.id,
                        Transaction.external_id.in_(batch),
                    )
                ).all()
                if value is not None
            )

    imported = 0
    for item in prepared:
        fingerprint = str(item["fingerprint"])
        if fingerprint in existing:
            skipped += 1
            continue
        category = item["category"]
        tx = Transaction(
            user_id=user.id,
            account_id=account.id,
            category_id=category.id if isinstance(category, Category) else None,
            user_category_override_id=None,
            external_id=fingerprint,
            pending_transaction_external_id=None,
            posted_date=item["posted_date"],
            authorized_date=None,
            merchant=item["merchant"],
            display_merchant=None,
            description=item["description"],
            original_description=None,
            payment_channel=None,
            pfc_primary=None,
            pfc_detailed=None,
            pfc_confidence=None,
            amount=item["amount"],
            kind=item["kind"],
            user_kind_override=None,
            excluded_from_spending=False,
            applied_rule_id=None,
            source_type="manual",
            pending=False,
            notes=item["notes"],
            imported_at=utc_now(),
        )
        db.add(tx)
        imported += 1
    db.flush()
    return {
        "total_rows": total,
        "imported": imported,
        "skipped_duplicates": skipped,
        "errors": errors,
    }


def bundle_json(bundle: dict[str, object]) -> str:
    return json.dumps(bundle, indent=2, ensure_ascii=False, default=str) + "\n"
