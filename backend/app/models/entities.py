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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    authorized_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(12), default="manual", nullable=False)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[Account] = relationship(viewonly=True)
    category: Mapped[Category | None] = relationship(viewonly=True)
