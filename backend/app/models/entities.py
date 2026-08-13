from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

MONEY = Numeric(19, 4)


class InstallationState(Base):
    __tablename__ = "installation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    settings: Mapped[UserSettings] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("theme IN ('light','dark','system')", name="theme_allowed"),
        CheckConstraint(
            "pay_frequency IS NULL OR pay_frequency IN "
            "('weekly','biweekly','semimonthly','monthly','annual')",
            name="pay_frequency_allowed",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    theme: Mapped[str] = mapped_column(String(10), default="system", nullable=False)
    annual_gross_income: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    pay_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="settings")


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_expires", "user_id", "absolute_expires_at"),
        Index("ix_sessions_idle_expires", "idle_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship()


class LoginThrottle(Base):
    __tablename__ = "login_throttles"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_created_action", "created_at", "action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinancialInstitution(TimestampMixin, Base):
    __tablename__ = "financial_institutions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_institution_id_user"),
        UniqueConstraint("user_id", "external_id", name="uq_institution_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    logo_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)


class PlaidItem(TimestampMixin, Base):
    __tablename__ = "plaid_items"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_plaid_item_id_user"),
        UniqueConstraint("user_id", "external_id", name="uq_plaid_item_external"),
        ForeignKeyConstraint(
            ["institution_id", "user_id"],
            ["financial_institutions.id", "financial_institutions.user_id"],
            name="fk_plaid_item_institution_owner",
        ),
        CheckConstraint("status IN ('active','error')", name="plaid_item_status_allowed"),
        Index("ix_plaid_items_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    institution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consent_expiration_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transactions_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transactions_update_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transactions_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transactions_last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sync_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webhook_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)

    institution: Mapped[FinancialInstitution | None] = relationship(viewonly=True)


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_account_external"),
        UniqueConstraint("id", "user_id", name="uq_account_id_user"),
        ForeignKeyConstraint(
            ["institution_id", "user_id"],
            ["financial_institutions.id", "financial_institutions.user_id"],
            name="fk_account_institution_owner",
        ),
        ForeignKeyConstraint(
            ["plaid_item_id", "user_id"],
            ["plaid_items.id", "plaid_items.user_id"],
            name="fk_account_plaid_item_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "account_type IN ('depository','credit','loan','investment','other')",
            name="account_type_allowed",
        ),
        CheckConstraint(
            "source_type IN ('manual','plaid')",
            name="account_source_type_allowed",
        ),
        Index("ix_accounts_user_type", "user_id", "account_type"),
        Index("ix_accounts_user_source", "user_id", "source_type"),
        Index("ix_accounts_user_plaid_item", "user_id", "plaid_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plaid_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_subtype: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_type: Mapped[str] = mapped_column(String(12), default="manual", nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    available_balance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    mask_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    institution: Mapped[FinancialInstitution | None] = relationship(viewonly=True)
    plaid_item: Mapped[PlaidItem | None] = relationship(viewonly=True)


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "stable_key", name="uq_category_user_key"),
        UniqueConstraint("id", "user_id", name="uq_category_id_user"),
        Index("ix_categories_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), default="circle", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_transaction_account_external"),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_transaction_account_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_transaction_category_owner",
        ),
        ForeignKeyConstraint(
            ["user_category_override_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_transaction_override_category_owner",
        ),
        CheckConstraint("kind IN ('income','expense','transfer','refund')", name="kind_allowed"),
        CheckConstraint(
            "source_type IN ('manual','plaid')",
            name="transaction_source_type_allowed",
        ),
        CheckConstraint(
            "(kind IN ('income','refund') AND amount >= 0) "
            "OR (kind = 'expense' AND amount <= 0) OR kind = 'transfer'",
            name="amount_sign",
        ),
        Index("ix_transactions_user_posted", "user_id", "posted_date"),
        Index("ix_transactions_user_account_posted", "user_id", "account_id", "posted_date"),
        Index("ix_transactions_user_category_posted", "user_id", "category_id", "posted_date"),
        Index("ix_transactions_user_source_posted", "user_id", "source_type", "posted_date"),
        Index("ix_transactions_user_external", "user_id", "external_id"),
        Index("ix_transactions_user_override_category", "user_id", "user_category_override_id"),
        Index(
            "ix_transactions_user_pending_external",
            "user_id",
            "pending_transaction_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_category_override_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pending_transaction_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    authorized_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    display_merchant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    original_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payment_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pfc_primary: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pfc_detailed: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pfc_confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    user_kind_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    excluded_from_spending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(12), default="manual", nullable=False)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[Account] = relationship(viewonly=True)
    category: Mapped[Category | None] = relationship(viewonly=True, foreign_keys=[category_id])
    user_category_override: Mapped[Category | None] = relationship(
        viewonly=True, foreign_keys=[user_category_override_id]
    )


class TransactionRule(TimestampMixin, Base):
    __tablename__ = "transaction_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_transaction_rule_category_owner",
        ),
        CheckConstraint(
            "match_field IN ('merchant','description','either')",
            name="transaction_rule_match_field_allowed",
        ),
        CheckConstraint(
            "kind_override IS NULL OR kind_override IN ('income','expense','transfer','refund')",
            name="transaction_rule_kind_allowed",
        ),
        Index("ix_transaction_rules_user_priority", "user_id", "enabled", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    match_field: Mapped[str] = mapped_column(String(16), default="either", nullable=False)
    pattern: Mapped[str] = mapped_column(String(160), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_merchant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    excluded_from_spending: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    category: Mapped[Category | None] = relationship(viewonly=True)


class RecurringStream(TimestampMixin, Base):
    __tablename__ = "recurring_streams"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_recurring_stream_account_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "kind IN ('income','expense')", name="recurring_stream_kind_allowed"
        ),
        CheckConstraint(
            "cadence IN ('weekly','biweekly','monthly','quarterly','annual')",
            name="recurring_stream_cadence_allowed",
        ),
        UniqueConstraint(
            "user_id", "account_id", "merchant_key", "kind", "cadence",
            name="uq_recurring_stream_identity",
        ),
        Index("ix_recurring_streams_user_next", "user_id", "active", "next_expected_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    merchant_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    average_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    last_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    last_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    price_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    account: Mapped[Account] = relationship(viewonly=True)


class AnnualBudgetPlan(TimestampMixin, Base):
    __tablename__ = "annual_budget_plans"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_annual_budget_plan_id_user"),
        UniqueConstraint("user_id", "year", name="uq_annual_budget_plan_user_year"),
        CheckConstraint("year >= 2000 AND year <= 2200", name="annual_budget_plan_year_range"),
        Index("ix_annual_budget_plans_user_year", "user_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_income: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnnualBudgetCategory(TimestampMixin, Base):
    __tablename__ = "annual_budget_categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["annual_budget_plans.id", "annual_budget_plans.user_id"],
            name="fk_annual_budget_category_plan_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_annual_budget_category_category_owner",
        ),
        UniqueConstraint("plan_id", "category_id", name="uq_annual_budget_category_plan_category"),
        CheckConstraint(
            "distribution IN ('even','monthly','custom')",
            name="annual_budget_category_distribution_allowed",
        ),
        CheckConstraint(
            "rollover_mode IN ('off','surplus','surplus_and_deficit')",
            name="annual_budget_category_rollover_allowed",
        ),
        Index("ix_annual_budget_categories_user_plan", "user_id", "plan_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    distribution: Mapped[str] = mapped_column(String(16), default="even", nullable=False)
    monthly_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    rollover_mode: Mapped[str] = mapped_column(String(24), default="off", nullable=False)

    category: Mapped[Category] = relationship(viewonly=True)


class AnnualBudgetMonthAllocation(Base):
    __tablename__ = "annual_budget_month_allocations"
    __table_args__ = (
        UniqueConstraint(
            "annual_category_id", "month_number", name="uq_annual_budget_month_allocation"
        ),
        CheckConstraint(
            "month_number >= 1 AND month_number <= 12",
            name="annual_budget_month_number_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    annual_category_id: Mapped[int] = mapped_column(
        ForeignKey("annual_budget_categories.id", ondelete="CASCADE"), nullable=False
    )
    month_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class MonthlyBudget(TimestampMixin, Base):
    __tablename__ = "monthly_budgets"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_monthly_budget_id_user"),
        UniqueConstraint("user_id", "month", name="uq_monthly_budget_user_month"),
        CheckConstraint("mode IN ('standalone','override')", name="monthly_budget_mode_allowed"),
        Index("ix_monthly_budgets_user_month", "user_id", "month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="standalone", nullable=False)
    planned_income: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MonthlyBudgetCategory(TimestampMixin, Base):
    __tablename__ = "monthly_budget_categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["budget_id", "user_id"],
            ["monthly_budgets.id", "monthly_budgets.user_id"],
            name="fk_monthly_budget_category_budget_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_monthly_budget_category_category_owner",
        ),
        UniqueConstraint("budget_id", "category_id", name="uq_monthly_budget_category_budget_category"),
        CheckConstraint(
            "rollover_mode IN ('off','surplus','surplus_and_deficit')",
            name="monthly_budget_category_rollover_allowed",
        ),
        Index("ix_monthly_budget_categories_user_budget", "user_id", "budget_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rollover_mode: Mapped[str] = mapped_column(String(24), default="off", nullable=False)

    category: Mapped[Category] = relationship(viewonly=True)
class FinancialGoal(TimestampMixin, Base):
    __tablename__ = "financial_goals"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_financial_goal_id_user"),
        UniqueConstraint(
            "user_id", "linked_account_id", name="uq_financial_goal_linked_account"
        ),
        CheckConstraint(
            "goal_type IN ('emergency_fund','savings','down_payment','vacation',"
            "'purchase','custom')",
            name="financial_goal_type_allowed",
        ),
        CheckConstraint("target_amount > 0", name="financial_goal_target_positive"),
        CheckConstraint("current_amount >= 0", name="financial_goal_current_nonnegative"),
        CheckConstraint("monthly_contribution >= 0", name="financial_goal_monthly_nonnegative"),
        Index("ix_financial_goals_user_active", "user_id", "active", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    linked_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(24), default="savings", nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    monthly_contribution: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0"), nullable=False
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    linked_account: Mapped[Account | None] = relationship(viewonly=True)


class GoalContribution(Base):
    __tablename__ = "goal_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["financial_goals.id", "financial_goals.user_id"],
            name="fk_goal_contribution_goal_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint("amount > 0", name="goal_contribution_amount_positive"),
        Index("ix_goal_contributions_user_date", "user_id", "contribution_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contribution_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Debt(TimestampMixin, Base):
    __tablename__ = "debts"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_debt_id_user"),
        UniqueConstraint("user_id", "linked_account_id", name="uq_debt_linked_account"),
        CheckConstraint(
            "debt_type IN ('credit_card','auto','student','personal','mortgage','medical','other')",
            name="debt_type_allowed",
        ),
        CheckConstraint("balance >= 0", name="debt_balance_nonnegative"),
        CheckConstraint("apr >= 0 AND apr <= 100", name="debt_apr_range"),
        CheckConstraint("minimum_payment >= 0", name="debt_minimum_nonnegative"),
        CheckConstraint("extra_payment >= 0", name="debt_extra_nonnegative"),
        CheckConstraint(
            "due_day IS NULL OR (due_day >= 1 AND due_day <= 31)",
            name="debt_due_day_range",
        ),
        Index("ix_debts_user_active", "user_id", "active", "strategy_priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    linked_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    debt_type: Mapped[str] = mapped_column(String(24), default="other", nullable=False)
    balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    apr: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"), nullable=False)
    minimum_payment: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    extra_payment: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    strategy_priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    linked_account: Mapped[Account | None] = relationship(viewonly=True)


class DebtStrategySettings(TimestampMixin, Base):
    __tablename__ = "debt_strategy_settings"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('avalanche','snowball','custom')",
            name="debt_strategy_allowed",
        ),
        CheckConstraint("monthly_extra_budget >= 0", name="debt_strategy_extra_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    strategy: Mapped[str] = mapped_column(String(16), default="avalanche", nullable=False)
    monthly_extra_budget: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0"), nullable=False
    )


class ForecastAssumptions(TimestampMixin, Base):
    __tablename__ = "forecast_assumptions"
    __table_args__ = (
        CheckConstraint("reserve_balance >= 0", name="forecast_reserve_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    reserve_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    include_budget_reserve: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
