from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Database
from app.core.security import hash_password, normalize_identity, utc_now
from app.models import Account, AuditEvent, Transaction, User, UserSettings
from app.services.security_audit import security_posture
from tests.conftest import csrf_headers


def test_api_responses_are_non_cacheable_and_cross_site_writes_are_blocked(
    client: TestClient,
) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-permitted-cross-domain-policies"] == "none"
    assert "default-src 'none'" in response.headers["content-security-policy"]

    blocked = client.post(
        "/api/v1/auth/login",
        headers={"Sec-Fetch-Site": "cross-site"},
        json={"identity": "owner", "password": "anything"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "cross_site_request"


def test_request_content_length_guard_rejects_oversized_requests(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Content-Length": "4500001"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"

    malformed = client.get("/api/health", headers={"Content-Length": "not-a-number"})
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "content_length_invalid"


def test_sensitive_portability_exports_are_audited(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    assert client.get("/api/v1/privacy/export").status_code == 200
    assert client.get("/api/v1/privacy/transactions.csv").status_code == 200

    with database.session_factory() as db:
        actions = list(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.action.in_(["privacy.export.all", "privacy.export.transactions"])
                )
            ).all()
        )
    assert actions == ["privacy.export.all", "privacy.export.transactions"]


def test_cross_user_financial_resource_ids_are_not_addressable(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    with database.session_factory() as db:
        other = User(
            username="family",
            normalized_username=normalize_identity("family"),
            email="family@example.com",
            normalized_email=normalize_identity("family@example.com"),
            password_hash=hash_password("Another Correct Horse Battery!"),
            is_admin=False,
            settings=UserSettings(currency="USD", timezone="America/Chicago", theme="system"),
        )
        db.add(other)
        db.flush()
        account = Account(
            user_id=other.id,
            name="Other User Checking",
            account_type="depository",
            account_subtype="checking",
            source_type="manual",
            current_balance=Decimal("100.0000"),
            currency="USD",
        )
        db.add(account)
        db.flush()
        transaction = Transaction(
            user_id=other.id,
            account_id=account.id,
            posted_date=date(2026, 8, 15),
            description="Other user's private transaction",
            amount=Decimal("-12.3400"),
            kind="expense",
            source_type="manual",
            pending=False,
            excluded_from_spending=False,
            imported_at=utc_now(),
        )
        db.add(transaction)
        db.commit()
        account_id = account.id
        transaction_id = transaction.id

    account_response = client.patch(
        f"/api/v1/accounts/{account_id}",
        headers=csrf_headers(csrf),
        json={"name": "stolen"},
    )
    assert account_response.status_code == 404

    transaction_response = client.patch(
        f"/api/v1/transactions/{transaction_id}",
        headers=csrf_headers(csrf),
        json={"description": "stolen"},
    )
    assert transaction_response.status_code == 404

    with database.session_factory() as db:
        assert db.get(Account, account_id).name == "Other User Checking"
        assert db.get(Transaction, transaction_id).description == "Other user's private transaction"


def test_security_posture_is_secret_free(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    settings = client.app.state.settings
    with database.session_factory() as db:
        result = security_posture(db, settings)

    rendered = repr(result)
    assert settings.secret_value("app_secret") not in rendered
    assert settings.secret_value("session_secret") not in rendered
    assert settings.secret_value("encryption_key") not in rendered
    assert result["ready"] is True
    assert result["summary"]["fail"] == 0
