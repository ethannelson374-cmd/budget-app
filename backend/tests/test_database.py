from __future__ import annotations

import warnings
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, joinedload

from app.core.database import Database
from app.core.security import hash_password, utc_now
from app.models import Account, Category, FinancialInstitution, Transaction, User, UserSettings


def add_user(db, name: str) -> User:
    user = User(
        username=name,
        normalized_username=name,
        email=f"{name}@example.com",
        normalized_email=f"{name}@example.com",
        password_hash=hash_password("A sufficiently long password"),
        settings=UserSettings(currency="USD", timezone="UTC", theme="system"),
    )
    db.add(user)
    db.flush()
    return user


def test_mapper_configuration_is_warning_free() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        configure_mappers()


def test_composite_foreign_keys_prevent_cross_user_ownership(database: Database) -> None:
    with database.session_factory() as db:
        owner = add_user(db, "owner-a")
        attacker = add_user(db, "owner-b")
        institution = FinancialInstitution(user_id=owner.id, name="Owner Bank")
        db.add(institution)
        db.flush()
        db.add(
            Account(
                user_id=attacker.id,
                institution_id=institution.id,
                name="Invalid",
                account_type="depository",
                current_balance=Decimal("1"),
                currency="USD",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_transaction_owner_and_sign_constraints(database: Database) -> None:
    with database.session_factory() as db:
        first = add_user(db, "first")
        second = add_user(db, "second")
        account = Account(
            user_id=first.id,
            name="Checking",
            account_type="depository",
            current_balance=Decimal("10"),
            currency="USD",
        )
        category = Category(
            user_id=first.id, stable_key="other", name="Other", icon="circle", enabled=True
        )
        db.add_all([account, category])
        db.commit()
        db.add(
            Transaction(
                user_id=second.id,
                account_id=account.id,
                category_id=category.id,
                posted_date=date.today(),
                description="Cross-user transaction",
                amount=Decimal("-1"),
                kind="expense",
                pending=False,
                imported_at=utc_now(),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "first"))
        assert user is not None
        account = db.scalar(select(Account).where(Account.user_id == user.id))
        category = db.scalar(select(Category).where(Category.user_id == user.id))
        db.add(
            Transaction(
                user_id=user.id,
                account_id=account.id,
                category_id=category.id,
                posted_date=date.today(),
                description="Wrong sign",
                amount=Decimal("5"),
                kind="expense",
                pending=False,
                imported_at=utc_now(),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_joined_relationships_load_after_composite_fk(database: Database) -> None:
    with database.session_factory() as db:
        user = add_user(db, "joined")
        account = Account(
            user_id=user.id,
            name="Checking",
            account_type="depository",
            current_balance=Decimal("10"),
            currency="USD",
        )
        category = Category(
            user_id=user.id, stable_key="other", name="Other", icon="circle", enabled=True
        )
        db.add_all([account, category])
        db.flush()
        item = Transaction(
            user_id=user.id,
            account_id=account.id,
            category_id=category.id,
            posted_date=date.today(),
            description="Purchase",
            amount=Decimal("-1"),
            kind="expense",
            pending=False,
            imported_at=utc_now(),
        )
        db.add(item)
        db.commit()
        loaded = db.scalar(
            select(Transaction)
            .options(joinedload(Transaction.account), joinedload(Transaction.category))
            .where(Transaction.id == item.id)
        )
        assert loaded is not None
        assert loaded.account.name == "Checking"
        assert loaded.category is not None and loaded.category.name == "Other"
