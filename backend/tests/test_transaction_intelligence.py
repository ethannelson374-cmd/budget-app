from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import date, timedelta
from decimal import Decimal

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.config import Settings
from app.core.plaid_webhook import PlaidWebhookVerificationError, verify_plaid_webhook
from app.models import Account, Category, RecurringStream, Transaction, TransactionRule, User
from app.services.transaction_intelligence import (
    apply_rules_to_transaction,
    rebuild_recurring_streams,
)
from tests.conftest import csrf_headers


def _owner(database) -> User:
    with database.session_factory() as db:
        user = db.scalar(select(User).options(joinedload(User.settings)))
        assert user is not None
        db.expunge(user)
        return user


def test_transaction_override_rules_and_recurring_api(authenticated, database) -> None:
    client, csrf = authenticated
    with database.session_factory() as db:
        user = db.scalar(select(User).options(joinedload(User.settings)))
        assert user is not None
        groceries = db.scalar(
            select(Category).where(Category.user_id == user.id, Category.stable_key == "groceries")
        )
        restaurants = db.scalar(
            select(Category).where(Category.user_id == user.id, Category.stable_key == "restaurants")
        )
        assert groceries is not None and restaurants is not None
        account = Account(
            user_id=user.id,
            name="Checking",
            account_type="depository",
            source_type="plaid",
            current_balance=Decimal("1000"),
            currency="USD",
        )
        db.add(account)
        db.flush()
        start = date(2026, 5, 1)
        transactions: list[Transaction] = []
        for index in range(4):
            transaction = Transaction(
                user_id=user.id,
                account_id=account.id,
                category_id=restaurants.id,
                posted_date=start + timedelta(days=30 * index),
                merchant="WM SUPERCENTER #1234 TULSA OK",
                description="WM SUPERCENTER #1234 TULSA OK",
                amount=Decimal("-100.00") - Decimal(index),
                kind="expense",
                source_type="plaid",
                pending=False,
                imported_at=user.created_at,
            )
            db.add(transaction)
            transactions.append(transaction)
        db.commit()
        transaction_id = transactions[0].id
        groceries_id = groceries.id

    override = client.patch(
        f"/api/v1/transactions/{transaction_id}/intelligence",
        headers=csrf_headers(csrf),
        json={
            "category_id": groceries_id,
            "display_merchant": "Walmart",
            "kind_override": "transfer",
            "excluded_from_spending": True,
        },
    )
    assert override.status_code == 200, override.text
    assert override.json()["merchant"] == "Walmart"
    assert override.json()["kind"] == "transfer"
    assert override.json()["category"]["key"] == "groceries"
    assert override.json()["excluded_from_spending"] is True

    created = client.post(
        "/api/v1/transaction-rules",
        headers=csrf_headers(csrf),
        json={
            "name": "Walmart groceries",
            "match_field": "either",
            "pattern": "WM SUPERCENTER",
            "category_id": groceries_id,
            "display_merchant": "Walmart",
            "priority": 10,
        },
    )
    assert created.status_code == 201, created.text
    rules = created.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["display_merchant"] == "Walmart"

    with database.session_factory() as db:
        applied = db.scalars(
            select(Transaction).where(
                Transaction.user_id == 1,
                Transaction.applied_rule_id == rules[0]["id"],
            )
        ).all()
        # The explicitly overridden transaction is left alone; the other three are automated.
        assert len(applied) == 3
        assert all(item.display_merchant == "Walmart" for item in applied)
        user = db.get(User, 1)
        assert user is not None
        rebuild_recurring_streams(db, user)
        db.commit()
        streams = db.scalars(select(RecurringStream)).all()
        assert len(streams) == 1
        assert streams[0].cadence == "monthly"
        assert streams[0].display_name == "Walmart"

    recurring = client.get("/api/v1/recurring")
    assert recurring.status_code == 200
    assert recurring.json()["streams"][0]["cadence"] == "monthly"
    assert Decimal(recurring.json()["monthly_outflow_estimate"]) > 0

    deleted = client.delete(
        f"/api/v1/transaction-rules/{rules[0]['id']}", headers=csrf_headers(csrf)
    )
    assert deleted.status_code == 200
    assert deleted.json()["rules"] == []


def test_rule_requires_action(authenticated) -> None:
    client, csrf = authenticated
    response = client.post(
        "/api/v1/transaction-rules",
        headers=csrf_headers(csrf),
        json={"name": "No-op", "match_field": "merchant", "pattern": "test"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "rule_has_no_action"


def test_plaid_webhook_verification_and_sync_hint(monkeypatch, authenticated, database) -> None:
    client, _csrf = authenticated
    settings = client.app.state.settings
    # Test app settings are not Plaid-configured by default; add a dedicated configured verifier settings.
    configured = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=settings.demo_db_path,
        allowed_hosts="testserver,localhost",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
        plaid_client_id="client",
        plaid_secret="secret",
        plaid_redirect_uri="http://localhost/plaid/oauth",
    )

    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "alg": "ES256",
        "crv": "P-256",
        "kid": "test-key",
        "kty": "EC",
        "use": "sig",
        "x": b64(public.x),
        "y": b64(public.y),
        "created_at": int(time.time()) - 10,
        "expired_at": None,
    }

    from app.core import plaid_webhook

    plaid_webhook._KEY_CACHE.clear()
    monkeypatch.setattr(
        "app.integrations.plaid.PlaidClient.webhook_verification_key_get",
        lambda self, key_id: {"key": jwk, "request_id": "request"},
    )
    body = json.dumps(
        {
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "SYNC_UPDATES_AVAILABLE",
            "item_id": "item-test",
        },
        separators=(",", ":"),
    ).encode()
    now = int(time.time())
    token = jwt.encode(
        {"iat": now, "request_body_sha256": hashlib.sha256(body).hexdigest()},
        private,
        algorithm="ES256",
        headers={"kid": "test-key", "typ": "JWT"},
    )
    claims = verify_plaid_webhook(configured, token, body, now=now)
    assert claims["iat"] == now
    try:
        verify_plaid_webhook(configured, token, body + b" ", now=now)
    except PlaidWebhookVerificationError:
        pass
    else:
        raise AssertionError("tampered webhook body should be rejected")
