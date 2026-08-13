from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.security import as_utc
from app.models import Account, Transaction, User, UserSettings

CENT_4 = Decimal("0.0001")


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(CENT_4, rounding=ROUND_HALF_UP), "f")


def settings_view(settings: UserSettings) -> dict[str, object]:
    return {
        "currency": settings.currency,
        "timezone": settings.timezone,
        "theme": settings.theme,
        "annual_gross_income": money(settings.annual_gross_income),
        "pay_frequency": settings.pay_frequency,
    }


def user_view(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "settings": settings_view(user.settings),
    }


def account_view(account: Account) -> dict[str, object]:
    mask = f"\u2022\u2022\u2022\u2022 {account.mask_last4}" if account.mask_last4 else None
    display_name = f"{account.name} {mask}" if mask else account.name
    return {
        "id": account.id,
        "institution": account.institution.name if account.institution else None,
        "name": account.name,
        "official_name": account.official_name,
        "display_name": display_name,
        "account_type": account.account_type,
        "account_subtype": account.account_subtype,
        "source_type": account.source_type,
        "current_balance": money(account.current_balance),
        "available_balance": money(account.available_balance),
        "credit_limit": money(account.credit_limit),
        "currency": account.currency,
        "mask": mask,
        "last_synced_at": as_utc(account.last_synced_at) if account.last_synced_at else None,
    }


def transaction_view(transaction: Transaction) -> dict[str, object]:
    account_mask = (
        f"\u2022\u2022\u2022\u2022 {transaction.account.mask_last4}"
        if transaction.account.mask_last4
        else None
    )
    return {
        "id": transaction.id,
        "posted_date": transaction.posted_date,
        "authorized_date": transaction.authorized_date,
        "merchant": transaction.merchant,
        "description": transaction.description,
        "amount": money(transaction.amount),
        "kind": transaction.kind,
        "source_type": transaction.source_type,
        "pending": transaction.pending,
        "notes": transaction.notes,
        "account": {
            "id": transaction.account.id,
            "name": transaction.account.name,
            "display_name": (
                f"{transaction.account.name} {account_mask}"
                if account_mask
                else transaction.account.name
            ),
            "mask": account_mask,
            "currency": transaction.account.currency,
        },
        "category": (
            {
                "id": transaction.category.id,
                "key": transaction.category.stable_key,
                "name": transaction.category.name,
            }
            if transaction.category
            else None
        ),
    }
