from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
from app.models import Account, Category
from app.schemas.api import (
    AccountCreate,
    AccountPatch,
    AccountView,
    AccountsView,
    CategorySelectionUpdate,
    CategorySelectionView,
    CashFlowSankeyView,
    DashboardOnboardingView,
    DashboardPreferencesUpdate,
    DashboardPreferencesView,
    DashboardView,
    OkView,
    OnboardingProgressRequest,
    OnboardingStatusView,
    SettingsPatch,
    SubscriptionUpdateRequest,
    SubscriptionsView,
    TransactionCreate,
    TransactionIntelligencePatch,
    TransactionPatch,
    TransactionRuleCreate,
    TransactionRulesView,
    RecurringStreamsView,
    TransactionPageView,
    TransactionView,
    UserSettingsView,
)
from app.services.auth import Principal, add_audit_event
from app.services.catalog import CATEGORY_BY_KEY, DEFAULT_CATEGORIES
from app.services.dashboard_experience import (
    dashboard_preferences,
    dismiss_onboarding,
    onboarding_status,
    save_dashboard_preferences,
)
from app.services.cash_flow import cash_flow_sankey
from app.services.finance import dashboard_data, transaction_page
from app.services.manual_finance import (
    create_manual_account,
    create_manual_transaction,
    delete_manual_account,
    delete_manual_transaction,
    update_manual_account,
    update_manual_transaction,
)
from app.services.setup import validate_category_keys
from app.services.subscriptions import is_subscription as stream_is_subscription, subscriptions_view, update_subscription
from app.services.transaction_intelligence import (
    create_rule,
    delete_rule,
    list_recurring_streams,
    list_rules,
    override_transaction,
    rebuild_recurring_streams,
)
from app.services.views import account_view, settings_view, transaction_view

router = APIRouter(tags=["finance"])


@router.get("/settings", response_model=UserSettingsView)
def get_user_settings(principal: Principal = Depends(require_principal)) -> dict[str, object]:
    return settings_view(principal.user.settings)


@router.patch("/settings", response_model=UserSettingsView)
def update_user_settings(
    payload: SettingsPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    current = principal.user.settings
    non_nullable = {"currency", "timezone", "theme", "advisor_enabled", "advisor_share_merchants", "advisor_share_planning_names", "advisor_include_descriptions", "advisor_store_history"}
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field in non_nullable and value is None:
            raise ApiError(422, "invalid_settings", f"{field} may not be null")
        setattr(current, field, value)
    if current.annual_gross_income is not None and current.pay_frequency is None:
        raise ApiError(
            422,
            "invalid_settings",
            "Pay frequency is required when annual gross income is set",
        )
    add_audit_event(
        db,
        settings,
        action="settings.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail="profile",
    )
    db.commit()
    return settings_view(current)


@router.get("/onboarding", response_model=OnboardingStatusView)
def get_onboarding_status(principal: Principal = Depends(require_principal)) -> dict[str, object]:
    return {"complete": principal.user.settings.onboarding_complete, "step": principal.user.settings.onboarding_step}


@router.patch("/onboarding", response_model=OnboardingStatusView)
def save_onboarding_progress(
    payload: OnboardingProgressRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    current = principal.user.settings
    if current.onboarding_complete:
        return {"complete": True, "step": current.onboarding_step}
    current.onboarding_step = max(current.onboarding_step, payload.step)
    add_audit_event(
        db, settings, action="onboarding.progress", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id,
        detail=f"step:{current.onboarding_step}",
    )
    db.commit()
    return {"complete": False, "step": current.onboarding_step}


@router.post("/onboarding/complete", response_model=OnboardingStatusView)
def complete_onboarding(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    current = principal.user.settings
    current.onboarding_complete = True
    current.onboarding_step = 6
    add_audit_event(
        db, settings, action="onboarding.complete", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail="first-run",
    )
    db.commit()
    return {"complete": True, "step": 6}


def _category_view(category: Category) -> dict[str, object]:
    definition = CATEGORY_BY_KEY.get(category.stable_key)
    return {
        "id": category.id,
        "key": category.stable_key,
        "name": category.name,
        "group": definition["group"] if definition else "Custom",
        "enabled": category.enabled,
    }


@router.get("/categories/selection", response_model=CategorySelectionView)
def get_category_selection(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    categories = list(
        db.scalars(
            select(Category)
            .where(Category.user_id == principal.budget_user.id)
            .order_by(Category.name, Category.id)
        ).all()
    )
    return {"categories": [_category_view(category) for category in categories]}


@router.put("/categories/selection", response_model=CategorySelectionView)
def update_category_selection(
    payload: CategorySelectionUpdate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    selected = validate_category_keys(payload.category_keys)
    categories = list(
        db.scalars(
            select(Category)
            .where(Category.user_id == principal.budget_user.id)
            .order_by(Category.name, Category.id)
        ).all()
    )
    existing = {category.stable_key for category in categories}
    for definition in DEFAULT_CATEGORIES:
        if definition["key"] not in existing:
            category = Category(
                user_id=principal.budget_user.id,
                stable_key=definition["key"],
                name=definition["name"],
                icon=definition["icon"],
                enabled=definition["key"] in selected,
            )
            db.add(category)
            categories.append(category)
    for category in categories:
        category.enabled = category.stable_key in selected
    add_audit_event(
        db,
        settings,
        action="categories.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail="selection",
    )
    db.commit()
    categories.sort(key=lambda item: (item.name, item.id or 0))
    return {"categories": [_category_view(category) for category in categories]}


@router.get("/accounts", response_model=AccountsView)
def get_accounts(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    accounts = db.scalars(
        select(Account)
        .options(joinedload(Account.institution))
        .where(Account.user_id == principal.budget_user.id)
        .order_by(Account.name, Account.id)
    ).all()
    return {"accounts": [account_view(account) for account in accounts]}


@router.post("/accounts", response_model=AccountView, status_code=201)
def create_account(
    payload: AccountCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    account = create_manual_account(db, principal.budget_user, payload.model_dump())
    add_audit_event(
        db,
        settings,
        action="account.create",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{account.id}",
    )
    db.commit()
    return account_view(account)


@router.patch("/accounts/{account_id}", response_model=AccountView)
def update_account(
    account_id: int,
    payload: AccountPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    account = update_manual_account(
        db,
        principal.budget_user,
        account_id,
        payload.model_dump(exclude_unset=True),
    )
    add_audit_event(
        db,
        settings,
        action="account.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{account.id}",
    )
    db.commit()
    return account_view(account)


@router.delete("/accounts/{account_id}", response_model=OkView)
def delete_account(
    account_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_manual_account(db, principal.budget_user, account_id)
    add_audit_event(
        db,
        settings,
        action="account.delete",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{account_id}",
    )
    db.commit()
    return {"ok": True}


@router.get("/cash-flow", response_model=CashFlowSankeyView)
def get_cash_flow(
    range_key: Annotated[Literal["month", "year", "custom"], Query(alias="range")] = "month",
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    start_date: date | None = None,
    end_date: date | None = None,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return cash_flow_sankey(
        db,
        principal.budget_user,
        range_key=range_key,
        month=month,
        year=year,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/dashboard", response_model=DashboardView)
def get_dashboard(
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return dashboard_data(db, principal.budget_user, month)


@router.get("/dashboard/preferences", response_model=DashboardPreferencesView)
def get_dashboard_preferences(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return dashboard_preferences(db, principal.user)


@router.put("/dashboard/preferences", response_model=DashboardPreferencesView)
def put_dashboard_preferences(
    payload: DashboardPreferencesUpdate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = save_dashboard_preferences(db, principal.user, cards=[card.model_dump() for card in payload.cards], preset=payload.preset)
    add_audit_event(db, settings, action="dashboard.preferences.update", outcome="success", request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=f"{payload.preset}:cards={len(payload.cards)}")
    db.commit()
    return result


@router.get("/dashboard/onboarding", response_model=DashboardOnboardingView)
def get_dashboard_onboarding(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return onboarding_status(db, principal.user)


@router.post("/dashboard/onboarding/dismiss", response_model=DashboardOnboardingView)
def post_dashboard_onboarding_dismiss(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = dismiss_onboarding(db, principal.user)
    add_audit_event(db, settings, action="dashboard.onboarding.dismiss", outcome="success", request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=f"completed={result['completed']}/{result['total']}")
    db.commit()
    return result


@router.get("/transactions", response_model=TransactionPageView)
def get_transactions(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: Annotated[int | None, Query(gt=0)] = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    kind: Literal["income", "expense", "transfer", "refund"] | None = None,
    pending: bool | None = None,
    sort: Literal["date", "amount", "merchant", "description"] = "date",
    direction: Literal["asc", "desc"] = "desc",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return transaction_page(
        db,
        principal.budget_user,
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        account_id=account_id,
        category_id=category_id,
        search=search,
        min_amount=min_amount,
        max_amount=max_amount,
        kind=kind,
        pending=pending,
        sort=sort,
        direction=direction,
    )


@router.post("/transactions", response_model=TransactionView, status_code=201)
def create_transaction(
    payload: TransactionCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    transaction = create_manual_transaction(db, principal.budget_user, payload.model_dump())
    add_audit_event(
        db,
        settings,
        action="transaction.create",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{transaction.id}",
    )
    db.commit()
    return transaction_view(transaction)


@router.patch("/transactions/{transaction_id}", response_model=TransactionView)
def update_transaction(
    transaction_id: int,
    payload: TransactionPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    transaction = update_manual_transaction(
        db,
        principal.budget_user,
        transaction_id,
        payload.model_dump(exclude_unset=True),
    )
    add_audit_event(
        db,
        settings,
        action="transaction.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{transaction.id}",
    )
    db.commit()
    return transaction_view(transaction)


@router.delete("/transactions/{transaction_id}", response_model=OkView)
def delete_transaction(
    transaction_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_manual_transaction(db, principal.budget_user, transaction_id)
    add_audit_event(
        db,
        settings,
        action="transaction.delete",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"manual:{transaction_id}",
    )
    db.commit()
    return {"ok": True}


@router.patch("/transactions/{transaction_id}/intelligence", response_model=TransactionView)
def update_transaction_intelligence(
    transaction_id: int,
    payload: TransactionIntelligencePatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    transaction = override_transaction(
        db,
        principal.budget_user,
        transaction_id,
        category_id=payload.category_id,
        category_supplied="category_id" in payload.model_fields_set,
        display_merchant=payload.display_merchant,
        merchant_supplied="display_merchant" in payload.model_fields_set,
        kind_override=payload.kind_override,
        kind_supplied="kind_override" in payload.model_fields_set,
        excluded_from_spending=payload.excluded_from_spending,
        excluded_supplied="excluded_from_spending" in payload.model_fields_set,
    )
    rebuild_recurring_streams(db, principal.budget_user)
    add_audit_event(
        db, settings, action="transaction.intelligence_update", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id,
        detail=f"transaction:{transaction_id}",
    )
    db.commit()
    return transaction_view(transaction)


def _rule_view(rule: object) -> dict[str, object]:
    from app.models import TransactionRule

    assert isinstance(rule, TransactionRule)
    return {
        "id": rule.id,
        "name": rule.name,
        "match_field": rule.match_field,
        "pattern": rule.pattern,
        "category": (
            {"id": rule.category.id, "key": rule.category.stable_key, "name": rule.category.name}
            if rule.category else None
        ),
        "display_merchant": rule.display_merchant,
        "kind_override": rule.kind_override,
        "excluded_from_spending": rule.excluded_from_spending,
        "priority": rule.priority,
        "enabled": rule.enabled,
    }


@router.get("/transaction-rules", response_model=TransactionRulesView)
def get_transaction_rules(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"rules": [_rule_view(rule) for rule in list_rules(db, principal.budget_user)]}


@router.post("/transaction-rules", response_model=TransactionRulesView, status_code=201)
def add_transaction_rule(
    payload: TransactionRuleCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    create_rule(
        db, principal.budget_user, name=payload.name, match_field=payload.match_field,
        pattern=payload.pattern, category_id=payload.category_id,
        display_merchant=payload.display_merchant, kind_override=payload.kind_override,
        excluded_from_spending=payload.excluded_from_spending, priority=payload.priority,
        enabled=payload.enabled,
    )
    rebuild_recurring_streams(db, principal.budget_user)
    add_audit_event(
        db, settings, action="transaction_rule.create", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id,
        detail="rule_created",
    )
    db.commit()
    return {"rules": [_rule_view(rule) for rule in list_rules(db, principal.budget_user)]}


@router.delete("/transaction-rules/{rule_id}", response_model=TransactionRulesView)
def remove_transaction_rule(
    rule_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    delete_rule(db, principal.budget_user, rule_id)
    rebuild_recurring_streams(db, principal.budget_user)
    add_audit_event(
        db, settings, action="transaction_rule.delete", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id,
        detail=f"rule:{rule_id}",
    )
    db.commit()
    return {"rules": [_rule_view(rule) for rule in list_rules(db, principal.budget_user)]}


def _monthly_equivalent(amount: Decimal, cadence: str) -> Decimal:
    factors = {
        "weekly": Decimal("4.345"), "biweekly": Decimal("2.1725"),
        "monthly": Decimal("1"), "quarterly": Decimal("0.333333"),
        "annual": Decimal("0.083333"),
    }
    return amount * factors[cadence]


@router.get("/recurring", response_model=RecurringStreamsView)
def recurring(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    streams = list_recurring_streams(db, principal.budget_user)
    outflow = Decimal("0")
    inflow = Decimal("0")
    items: list[dict[str, object]] = []
    for stream in streams:
        amount = _monthly_equivalent(stream.average_amount, stream.cadence)
        if stream.kind == "expense":
            outflow += amount
        else:
            inflow += amount
        mask = f"•••• {stream.account.mask_last4}" if stream.account.mask_last4 else None
        items.append({
            "id": stream.id, "display_name": stream.display_name, "kind": stream.kind,
            "cadence": stream.cadence, "average_amount": str(stream.average_amount),
            "last_amount": str(stream.last_amount), "last_date": stream.last_date,
            "next_expected_date": stream.next_expected_date,
            "occurrence_count": stream.occurrence_count,
            "price_change_pct": str(stream.price_change_pct) if stream.price_change_pct is not None else None,
            "is_subscription": stream_is_subscription(stream),
            "subscription_detected": bool(stream.subscription_detected),
            "subscription_override": stream.subscription_override,
            "subscription_status": stream.subscription_status,
            "account": {
                "id": stream.account.id, "name": stream.account.name,
                "display_name": f"{stream.account.name} {mask}" if mask else stream.account.name,
                "mask": mask, "currency": stream.account.currency,
            },
        })
    from app.services.views import money
    return {"currency": principal.budget_user.settings.currency, "streams": items, "monthly_outflow_estimate": money(outflow), "monthly_inflow_estimate": money(inflow)}


@router.get("/subscriptions", response_model=SubscriptionsView)
def subscriptions(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return subscriptions_view(db, principal.budget_user)


@router.patch("/recurring/{stream_id}/subscription", response_model=SubscriptionsView)
def patch_subscription(
    stream_id: int,
    payload: SubscriptionUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    if not payload.model_fields_set:
        raise ApiError(422, "subscription_update_empty", "Choose a subscription setting to update")
    update_subscription(
        db,
        principal.budget_user,
        stream_id,
        is_subscription_value=(
            payload.is_subscription if "is_subscription" in payload.model_fields_set else None
        ),
        status=payload.status if "status" in payload.model_fields_set else None,
    )
    add_audit_event(
        db,
        settings,
        action="subscription.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"stream:{stream_id}",
    )
    db.commit()
    return subscriptions_view(db, principal.budget_user)


@router.post("/recurring/rebuild", response_model=RecurringStreamsView)
def rebuild_recurring(
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    rebuild_recurring_streams(db, principal.budget_user)
    db.commit()
    return recurring(principal, db)
