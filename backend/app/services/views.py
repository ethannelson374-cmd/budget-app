from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.security import as_utc
from app.models import Account, Transaction, User, UserSettings
from app.services.transaction_intelligence import effective_category, effective_kind, effective_merchant

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
        "advisor_enabled": settings.advisor_enabled,
        "advisor_share_merchants": settings.advisor_share_merchants,
        "advisor_include_descriptions": settings.advisor_include_descriptions,
        "advisor_store_history": settings.advisor_store_history,
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
        "connection_id": account.plaid_item_id,
    }


def transaction_view(transaction: Transaction) -> dict[str, object]:
    account_mask = (
        f"\u2022\u2022\u2022\u2022 {transaction.account.mask_last4}"
        if transaction.account.mask_last4
        else None
    )
    category = effective_category(transaction)
    return {
        "id": transaction.id,
        "posted_date": transaction.posted_date,
        "authorized_date": transaction.authorized_date,
        "merchant": effective_merchant(transaction),
        "provider_merchant": transaction.merchant,
        "display_merchant": transaction.display_merchant,
        "description": transaction.description,
        "original_description": transaction.original_description,
        "payment_channel": transaction.payment_channel,
        "pfc_primary": transaction.pfc_primary,
        "pfc_detailed": transaction.pfc_detailed,
        "pfc_confidence": transaction.pfc_confidence,
        "amount": money(transaction.amount),
        "kind": effective_kind(transaction),
        "provider_kind": transaction.kind,
        "source_type": transaction.source_type,
        "pending": transaction.pending,
        "notes": transaction.notes,
        "excluded_from_spending": transaction.excluded_from_spending,
        "has_user_override": bool(
            transaction.user_category_override_id is not None
            or transaction.user_kind_override is not None
            or transaction.display_merchant is not None
            or transaction.excluded_from_spending
        ),
        "applied_rule_id": transaction.applied_rule_id,
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
            {"id": category.id, "key": category.stable_key, "name": category.name}
            if category
            else None
        ),
        "provider_category": (
            {
                "id": transaction.category.id,
                "key": transaction.category.stable_key,
                "name": transaction.category.name,
            }
            if transaction.category
            else None
        ),
    }
