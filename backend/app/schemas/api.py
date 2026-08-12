from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Theme = Literal["light", "dark", "system"]
PayFrequency = Literal["weekly", "biweekly", "semimonthly", "monthly", "annual"]
TransactionKind = Literal["income", "expense", "transfer", "refund"]


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
    current_balance: str
    available_balance: str | None
    credit_limit: str | None
    currency: str
    mask: str | None
    last_synced_at: datetime | None


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
    description: str
    amount: str
    kind: str
    pending: bool
    account: TransactionAccountView
    category: TransactionCategoryView | None


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
