from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Theme = Literal["light", "dark", "system"]
PayFrequency = Literal["weekly", "biweekly", "semimonthly", "monthly", "annual"]
TransactionKind = Literal["income", "expense", "transfer", "refund"]
AccountType = Literal["depository", "credit", "loan", "investment", "other"]
SourceType = Literal["manual", "plaid"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupRequest(StrictModel):
    username: Annotated[str, Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")]
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]
    currency: CurrencyCode = "USD"
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    theme: Theme = "system"
    annual_gross_income: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = (
        None
    )
    pay_frequency: PayFrequency | None = None
    category_keys: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=50
    )

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def require_frequency_for_income(self) -> SetupRequest:
        if self.annual_gross_income is not None and self.pay_frequency is None:
            raise ValueError("pay_frequency is required when annual_gross_income is set")
        return self


class LoginRequest(StrictModel):
    identity: Annotated[str, Field(min_length=1, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class SettingsPatch(StrictModel):
    currency: CurrencyCode | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    theme: Theme | None = None
    annual_gross_income: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = (
        None
    )
    pay_frequency: PayFrequency | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value


class CategorySelectionUpdate(StrictModel):
    category_keys: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=50)


class AccountCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    official_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    account_type: AccountType
    account_subtype: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    current_balance: Annotated[Decimal, Field(max_digits=19, decimal_places=4)] = Decimal("0")
    available_balance: Annotated[Decimal, Field(max_digits=19, decimal_places=4)] | None = None
    credit_limit: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = None
    currency: CurrencyCode = "USD"
    mask_last4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None

    @field_validator("name", "official_name", "account_subtype")
    @classmethod
    def strip_account_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_account_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AccountPatch(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    official_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    account_type: AccountType | None = None
    account_subtype: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    current_balance: Annotated[Decimal, Field(max_digits=19, decimal_places=4)] | None = None
    available_balance: Annotated[Decimal, Field(max_digits=19, decimal_places=4)] | None = None
    credit_limit: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = None
    currency: CurrencyCode | None = None
    mask_last4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None

    @field_validator("name", "official_name", "account_subtype")
    @classmethod
    def strip_account_patch_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_account_patch_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_account_change(self) -> AccountPatch:
        if not self.model_fields_set:
            raise ValueError("at least one account field must be supplied")
        return self


class TransactionCreate(StrictModel):
    account_id: Annotated[int, Field(gt=0)]
    category_id: Annotated[int, Field(gt=0)] | None = None
    posted_date: date
    authorized_date: date | None = None
    merchant: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    description: Annotated[str, Field(min_length=1, max_length=255)]
    amount: Annotated[Decimal, Field(max_digits=19, decimal_places=4)]
    kind: TransactionKind
    pending: bool = False
    notes: Annotated[str, Field(max_length=4000)] | None = None

    @field_validator("merchant", "description", "notes")
    @classmethod
    def strip_transaction_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_amount_sign(self) -> TransactionCreate:
        if self.kind in {"income", "refund"} and self.amount < 0:
            raise ValueError("income and refund amounts must be zero or positive")
        if self.kind == "expense" and self.amount > 0:
            raise ValueError("expense amounts must be zero or negative")
        return self


class TransactionPatch(StrictModel):
    account_id: Annotated[int, Field(gt=0)] | None = None
    category_id: Annotated[int, Field(gt=0)] | None = None
    posted_date: date | None = None
    authorized_date: date | None = None
    merchant: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    description: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    amount: Annotated[Decimal, Field(max_digits=19, decimal_places=4)] | None = None
    kind: TransactionKind | None = None
    pending: bool | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None

    @field_validator("merchant", "description", "notes")
    @classmethod
    def strip_transaction_patch_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_transaction_change(self) -> TransactionPatch:
        if not self.model_fields_set:
            raise ValueError("at least one transaction field must be supplied")
        return self


class UserSettingsView(ViewModel):
    currency: str
    timezone: str
    theme: str
    annual_gross_income: str | None
    pay_frequency: str | None


class UserView(ViewModel):
    id: int
    username: str
    email: str
    settings: UserSettingsView


class AuthView(ViewModel):
    user: UserView
    csrf_token: str


class AccountView(ViewModel):
    id: int
    institution: str | None
    name: str
    official_name: str | None
    display_name: str
    account_type: str
    account_subtype: str | None
    source_type: SourceType
    current_balance: str
    available_balance: str | None
    credit_limit: str | None
    currency: str
    mask: str | None
    last_synced_at: datetime | None
    connection_id: int | None


class PlaidLinkAccountMetadata(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    mask: Annotated[str, Field(min_length=2, max_length=4, pattern=r"^[A-Za-z0-9]+$")] | None = None


class PlaidExchangeRequest(StrictModel):
    public_token: SecretStr = Field(min_length=1, max_length=1024)
    institution_id: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    accounts: list[PlaidLinkAccountMetadata] = Field(default_factory=list, max_length=100)


class PlaidLinkTokenView(ViewModel):
    link_token: str
    environment: Literal["sandbox", "production"]


class PlaidInstitutionView(ViewModel):
    id: int | None
    name: str
    logo: str | None
    primary_color: str | None
    url: str | None


class PlaidConnectionView(ViewModel):
    id: int
    status: Literal["active", "error"]
    last_error_code: str | None
    last_synced_at: datetime | None
    transactions_update_status: str | None
    transactions_last_synced_at: datetime | None
    transactions_last_error_code: str | None
    institution: PlaidInstitutionView
    accounts: list[AccountView]


class PlaidSyncResultView(ViewModel):
    connection_id: int
    added: int
    modified: int
    removed: int
    update_status: str | None
    last_synced_at: datetime


class PlaidConnectionsView(ViewModel):
    configured: bool
    environment: Literal["sandbox", "production"]
    connections: list[PlaidConnectionView]


class TransactionAccountView(ViewModel):
    id: int
    name: str
    display_name: str
    mask: str | None
    currency: str


class TransactionCategoryView(ViewModel):
    id: int
    key: str
    name: str


class TransactionView(ViewModel):
    id: int
    posted_date: date
    authorized_date: date | None
    merchant: str | None
    provider_merchant: str | None
    display_merchant: str | None
    description: str
    original_description: str | None
    payment_channel: str | None
    pfc_primary: str | None
    pfc_detailed: str | None
    pfc_confidence: str | None
    amount: str
    kind: str
    provider_kind: str
    source_type: SourceType
    pending: bool
    notes: str | None
    excluded_from_spending: bool
    has_user_override: bool
    applied_rule_id: int | None
    account: TransactionAccountView
    category: TransactionCategoryView | None
    provider_category: TransactionCategoryView | None


class StatusView(ViewModel):
    status: str


class SetupStatusView(ViewModel):
    initialized: bool
    demo_mode: bool
    bootstrap_required: bool


class CurrencyOptionView(ViewModel):
    code: str
    name: str


class PayFrequencyOptionView(ViewModel):
    value: str
    label: str


class DefaultCategoryOptionView(ViewModel):
    key: str
    name: str
    group: str
    selected_by_default: bool


class SetupOptionsView(ViewModel):
    currencies: list[CurrencyOptionView]
    pay_frequencies: list[PayFrequencyOptionView]
    default_categories: list[DefaultCategoryOptionView]


class OkView(ViewModel):
    ok: bool


class CategoryView(ViewModel):
    id: int
    key: str
    name: str
    group: str
    enabled: bool


class CategorySelectionView(ViewModel):
    categories: list[CategoryView]


class AccountsView(ViewModel):
    accounts: list[AccountView]


class TransactionPageView(ViewModel):
    items: list[TransactionView]
    page: int
    page_size: int
    total: int
    pages: int


class DashboardPeriodView(ViewModel):
    month: str
    start: date
    end: date


class DashboardSummaryView(ViewModel):
    net_worth: str
    cash_available: str
    income: str
    spending: str
    net_cash_flow: str
    savings_rate: str | None


class CategoryTotalView(ViewModel):
    key: str
    name: str
    amount: str


class DailyCashFlowView(ViewModel):
    date: date
    amount: str


class DashboardView(ViewModel):
    period: DashboardPeriodView
    currency: str
    as_of: datetime
    summary: DashboardSummaryView
    spending_by_category: list[CategoryTotalView]
    daily_cash_flow: list[DailyCashFlowView]
    accounts: list[AccountView]
    recent_transactions: list[TransactionView]
    excluded_currencies: list[str]


class TransactionIntelligencePatch(StrictModel):
    category_id: Annotated[int, Field(gt=0)] | None = None
    display_merchant: Annotated[str, Field(max_length=160)] | None = None
    kind_override: TransactionKind | None = None
    excluded_from_spending: bool | None = None

    @field_validator("display_merchant")
    @classmethod
    def clean_display_merchant(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_intelligence_change(self) -> TransactionIntelligencePatch:
        if not self.model_fields_set:
            raise ValueError("at least one override field must be supplied")
        return self


class TransactionRuleCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    match_field: Literal["merchant", "description", "either"] = "either"
    pattern: Annotated[str, Field(min_length=1, max_length=160)]
    category_id: Annotated[int, Field(gt=0)] | None = None
    display_merchant: Annotated[str, Field(max_length=160)] | None = None
    kind_override: TransactionKind | None = None
    excluded_from_spending: bool | None = None
    priority: Annotated[int, Field(ge=0, le=10000)] = 100
    enabled: bool = True

    @field_validator("name", "pattern")
    @classmethod
    def clean_required_rule_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("display_merchant")
    @classmethod
    def clean_optional_rule_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TransactionRuleView(ViewModel):
    id: int
    name: str
    match_field: str
    pattern: str
    category: TransactionCategoryView | None
    display_merchant: str | None
    kind_override: str | None
    excluded_from_spending: bool | None
    priority: int
    enabled: bool


class TransactionRulesView(ViewModel):
    rules: list[TransactionRuleView]


class RecurringStreamView(ViewModel):
    id: int
    display_name: str
    kind: Literal["income", "expense"]
    cadence: Literal["weekly", "biweekly", "monthly", "quarterly", "annual"]
    average_amount: str
    last_amount: str
    last_date: date
    next_expected_date: date
    occurrence_count: int
    price_change_pct: str | None
    account: TransactionAccountView


class RecurringStreamsView(ViewModel):
    currency: str
    streams: list[RecurringStreamView]
    monthly_outflow_estimate: str
    monthly_inflow_estimate: str


RolloverMode = Literal["off", "surplus", "surplus_and_deficit"]
BudgetDistribution = Literal["even", "monthly", "custom"]
MonthlyBudgetMode = Literal["standalone", "override"]
BudgetStatus = Literal["on_track", "close", "over", "no_budget"]


class BudgetCustomMonthAmount(StrictModel):
    month: Annotated[int, Field(ge=1, le=12)]
    amount: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)]


class AnnualBudgetCategoryWrite(StrictModel):
    category_id: Annotated[int, Field(gt=0)]
    annual_amount: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] = Decimal("0")
    distribution: BudgetDistribution = "even"
    monthly_amount: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = None
    custom_months: list[BudgetCustomMonthAmount] = Field(default_factory=list, max_length=12)
    rollover_mode: RolloverMode = "off"

    @model_validator(mode="after")
    def validate_distribution(self) -> AnnualBudgetCategoryWrite:
        if self.distribution == "monthly" and self.monthly_amount is None:
            raise ValueError("monthly_amount is required for monthly distribution")
        if self.distribution == "custom":
            months = [item.month for item in self.custom_months]
            if len(months) != 12 or set(months) != set(range(1, 13)):
                raise ValueError("custom_months must contain each month from 1 through 12")
        return self


class AnnualBudgetPlanWrite(StrictModel):
    planned_income: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)]
    notes: Annotated[str, Field(max_length=2000)] | None = None
    categories: list[AnnualBudgetCategoryWrite] = Field(default_factory=list, max_length=100)


class BudgetCategoryRef(ViewModel):
    id: int
    key: str
    name: str
    group: str
    enabled: bool


class BudgetCustomMonthView(ViewModel):
    month: int
    amount: str


class AnnualBudgetCategoryView(ViewModel):
    category: BudgetCategoryRef
    annual_amount: str
    distribution: BudgetDistribution
    monthly_amount: str | None
    rollover_mode: RolloverMode
    custom_months: list[BudgetCustomMonthView]


class AnnualBudgetPlanView(ViewModel):
    year: int
    exists: bool
    planned_income: str
    notes: str | None
    categories: list[AnnualBudgetCategoryView]


class MonthlyBudgetCategoryWrite(StrictModel):
    category_id: Annotated[int, Field(gt=0)]
    planned_amount: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)]
    rollover_mode: RolloverMode = "off"


class MonthlyBudgetWrite(StrictModel):
    mode: MonthlyBudgetMode = "standalone"
    planned_income: Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)] | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None
    categories: list[MonthlyBudgetCategoryWrite] = Field(default_factory=list, max_length=100)


class MonthlyBudgetCategoryView(ViewModel):
    category: BudgetCategoryRef
    base_amount: str
    rollover_amount: str
    available_amount: str
    spent_amount: str
    remaining_amount: str
    percent_used: str | None
    status: BudgetStatus
    rollover_mode: RolloverMode


class MonthlyBudgetView(ViewModel):
    period: DashboardPeriodView
    currency: str
    source: Literal["annual", "standalone", "override", "unplanned"]
    monthly_mode: MonthlyBudgetMode | None
    has_annual_plan: bool
    planned_income: str
    actual_income: str
    budgeted: str
    available_with_rollover: str
    spent: str
    remaining: str
    unallocated: str
    cash_available: str
    upcoming_recurring: str
    safe_to_spend: str
    notes: str | None
    categories: list[MonthlyBudgetCategoryView]


class YearBudgetCategoryView(ViewModel):
    category: BudgetCategoryRef
    planned_amount: str
    ytd_planned_amount: str
    spent_amount: str
    remaining_amount: str
    percent_used: str | None


class YearBudgetView(ViewModel):
    year: int
    currency: str
    has_annual_plan: bool
    planned_income: str
    ytd_planned_income: str
    actual_income: str
    budgeted: str
    spent: str
    remaining: str
    unallocated: str
    categories: list[YearBudgetCategoryView]
