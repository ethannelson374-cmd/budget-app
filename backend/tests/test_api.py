from __future__ import annotations

import concurrent.futures
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import Database
from app.core.security import cookie_name, csrf_digest, utc_now
from app.models import Account, AuditEvent, Category, SessionRecord, Transaction, User
from tests.conftest import csrf_headers


def error_fields(response) -> set[str]:
    return set(response.json()["error"])


def test_phase_one_success_routes_declare_response_models(client: TestClient) -> None:
    required_paths = {
        "/api/health",
        "/api/ready",
        "/api/v1/setup/status",
        "/api/v1/setup/options",
        "/api/v1/setup",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/demo-login",
        "/api/v1/settings",
        "/api/v1/categories/selection",
        "/api/v1/dashboard",
        "/api/v1/accounts",
        "/api/v1/accounts/{account_id}",
        "/api/v1/transactions",
        "/api/v1/transactions/{transaction_id}",
        "/api/v1/plaid/link-token",
        "/api/v1/plaid/exchange",
        "/api/v1/plaid/connections",
        "/api/v1/plaid/connections/{item_id}",
        "/api/v1/plaid/webhook",
        "/api/v1/transactions/{transaction_id}/intelligence",
        "/api/v1/transaction-rules",
        "/api/v1/transaction-rules/{rule_id}",
        "/api/v1/recurring",
        "/api/v1/recurring/rebuild",
    }
    openapi_paths = client.app.openapi()["paths"]
    assert required_paths.issubset(openapi_paths)
    for path in required_paths:
        operations = openapi_paths[path].values()
        success_responses = [
            response
            for operation in operations
            for status, response in operation["responses"].items()
            if 200 <= int(status) < 300
        ]
        assert success_responses
        assert all(
            response["content"]["application/json"].get("schema") for response in success_responses
        )


def test_health_readiness_and_uniform_http_errors(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "healthy"}
    assert client.get("/api/ready").json() == {"status": "ready"}
    missing = client.get("/api/does-not-exist", headers={"X-Request-ID": "request-404"})
    assert missing.status_code == 404
    assert missing.headers["X-Request-ID"] == "request-404"
    assert missing.json()["error"]["request_id"] == "request-404"
    assert error_fields(missing) == {"code", "message", "request_id"}
    method = client.put("/api/health")
    assert method.status_code == 405
    assert error_fields(method) == {"code", "message", "request_id"}
    invalid_host = client.get("/api/health", headers={"Host": "evil.example"})
    assert invalid_host.status_code == 400
    assert invalid_host.json()["error"]["code"] == "invalid_host"
    assert error_fields(invalid_host) == {"code", "message", "request_id"}


def test_validation_error_is_generic_and_secret_safe(client: TestClient) -> None:
    sentinel = "secret-in-body-4c60dcec"
    response = client.post(
        "/api/v1/setup",
        json={"password": sentinel},
        headers={"X-Request-ID": "validation-case"},
    )
    assert response.status_code == 422
    assert sentinel not in response.text
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
            "request_id": "validation-case",
        }
    }


def test_setup_authenticates_and_never_persists_bootstrap_token(
    tmp_path, setup_payload: dict[str, object]
) -> None:
    bootstrap = "f0" * 32
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "bootstrap.db",
        bootstrap_token=bootstrap,
        allowed_hosts="testserver",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    from app.main import create_app
    from app.models import Base, InstallationState

    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    try:
        with TestClient(create_app(settings, database)) as test_client:
            assert test_client.post("/api/v1/setup", json=setup_payload).status_code == 403
            response = test_client.post(
                "/api/v1/setup",
                json=setup_payload,
                headers={"X-Bootstrap-Token": bootstrap},
            )
            assert response.status_code == 200
            assert response.json()["user"]["username"] == "owner"
            assert response.json()["csrf_token"]
            assert test_client.get("/api/v1/auth/me").status_code == 200
        with database.session_factory() as db:
            attempts = db.scalars(
                select(AuditEvent).where(AuditEvent.action == "installation.setup")
            ).all()
            assert [item.outcome for item in attempts] == ["blocked", "success"]
            assert all(item.detail in {"invalid_bootstrap_token", None} for item in attempts)
        raw_database = (tmp_path / "bootstrap.db").read_bytes()
        assert bootstrap.encode() not in raw_database
    finally:
        database.engine.dispose()


def test_initialized_setup_returns_409_even_if_token_removed(
    client: TestClient, setup_payload: dict[str, object]
) -> None:
    assert client.post("/api/v1/setup", json=setup_payload).status_code == 200
    response = client.post("/api/v1/setup", json=setup_payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_initialized"


def test_production_first_start_requires_token_but_initialized_start_does_not(
    tmp_path, setup_payload: dict[str, object]
) -> None:
    from app.main import create_app
    from app.models import Base, InstallationState

    settings = Settings(
        _env_file=None,
        app_env="production",
        demo_mode=False,
        allowed_hosts="testserver",
        app_secret="existing-app-secret",
        session_secret="existing-session-secret",
        encryption_key="existing-encryption-key",
        db_host="mysql.internal.example",
        db_port=3306,
        db_name="budget",
        db_user="budgetapp",
        db_password="not-used-by-injected-test-database",
        db_ssl_required=True,
        backup_dir=tmp_path / "backups",
    )
    test_database = Database.from_settings(
        Settings(
            _env_file=None,
            app_env="test",
            demo_db_path=tmp_path / "production-startup-test.db",
        )
    )
    Base.metadata.create_all(test_database.engine)
    with test_database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    try:
        with (
            pytest.raises(RuntimeError, match="Initial setup is unavailable"),
            TestClient(create_app(settings, test_database)),
        ):
            pass

        with test_database.session_factory() as db:
            state = db.get(InstallationState, 1)
            assert state is not None
            state.initialized_at = datetime.now(UTC)
            db.commit()
        with TestClient(
            create_app(settings, test_database), base_url="https://testserver"
        ) as production_client:
            assert production_client.get("/api/ready").status_code == 200
            response = production_client.post("/api/v1/setup", json=setup_payload)
            assert response.status_code == 409
    finally:
        test_database.engine.dispose()


def test_concurrent_setup_allows_one_owner(
    client: TestClient, setup_payload: dict[str, object], database: Database
) -> None:
    second = dict(setup_payload)
    second.update(username="second", email="second@example.com")

    def submit(payload: dict[str, object]) -> int:
        return client.post("/api/v1/setup", json=payload).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit, [setup_payload, second]))
    assert sorted(statuses) == [200, 409]
    with database.session_factory() as db:
        assert len(db.scalars(select(User)).all()) == 1


def test_login_is_non_enumerating_rate_limited_and_hmacs_keys(
    client: TestClient, setup_payload: dict[str, object], database: Database
) -> None:
    client.post("/api/v1/setup", json=setup_payload)
    client.cookies.clear()
    known = client.post("/api/v1/auth/login", json={"identity": "owner", "password": "wrong"})
    unknown = client.post(
        "/api/v1/auth/login", json={"identity": "does-not-exist", "password": "wrong"}
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json()["error"]["message"] == unknown.json()["error"]["message"]
    for _ in range(4):
        last = client.post("/api/v1/auth/login", json={"identity": "owner", "password": "wrong"})
    assert last.status_code in {401, 429}
    blocked = client.post("/api/v1/auth/login", json={"identity": "owner", "password": "wrong"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    with database.session_factory() as db:
        audit = db.scalars(select(AuditEvent)).all()
        assert all(item.subject_key != "owner" for item in audit)
        assert all(item.detail != "owner" for item in audit)


def test_csrf_origin_logout_and_session_storage(
    authenticated: tuple[TestClient, str], settings: Settings, database: Database
) -> None:
    client, csrf = authenticated
    cookie = client.cookies.get(cookie_name(settings))
    assert cookie is not None
    with database.session_factory() as db:
        session = db.scalar(select(SessionRecord))
        assert session is not None
        assert session.token_digest != cookie
        assert session.csrf_digest == csrf_digest(settings, csrf)
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers=csrf_headers(csrf, origin="http://evil.example"),
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/logout", headers=csrf_headers(csrf)).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_expiration_is_enforced(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    with database.session_factory() as db:
        record = db.scalar(select(SessionRecord))
        assert record is not None
        record.idle_expires_at = datetime(2000, 1, 1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def add_finance_data(database: Database) -> None:
    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        categories = {
            item.stable_key: item
            for item in db.scalars(select(Category).where(Category.user_id == user.id)).all()
        }
        checking = Account(
            user_id=user.id,
            name="Checking",
            account_type="depository",
            current_balance=Decimal("1000"),
            available_balance=Decimal("900"),
            currency="USD",
            mask_last4="1234",
            last_synced_at=datetime(2026, 8, 12, 12, 0),
        )
        euro = Account(
            user_id=user.id,
            name="Euro Account",
            account_type="depository",
            current_balance=Decimal("500"),
            available_balance=Decimal("500"),
            currency="EUR",
            mask_last4="9988",
        )
        db.add_all([checking, euro])
        db.flush()
        rows = [
            ("income", "income", "Employer", "Paycheck", "3000"),
            ("expense", "housing", "Landlord", "Rent", "-1200"),
            ("expense", "groceries", "Market", "Groceries", "-200"),
            ("refund", "groceries", "Market", "Refund", "25"),
            ("transfer", "other", "Transfer", "Savings transfer", "-300"),
        ]
        for index, (kind, category_key, merchant, description, amount) in enumerate(rows):
            db.add(
                Transaction(
                    user_id=user.id,
                    account_id=checking.id,
                    category_id=categories[category_key].id,
                    external_id=f"test-{index}",
                    posted_date=date(2026, 8, 5 + index),
                    description=description,
                    merchant=merchant,
                    amount=Decimal(amount),
                    kind=kind,
                    pending=False,
                    imported_at=utc_now(),
                )
            )
        db.commit()


def test_accounts_masking_and_naive_mysql_timestamp(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    add_finance_data(database)
    response = client.get("/api/v1/accounts")
    assert response.status_code == 200
    checking = next(item for item in response.json()["accounts"] if item["name"] == "Checking")
    assert checking["mask"] == "\u2022\u2022\u2022\u2022 1234"
    assert checking["display_name"] == "Checking \u2022\u2022\u2022\u2022 1234"
    assert checking["last_synced_at"].endswith("Z") or checking["last_synced_at"].endswith("+00:00")


def test_dashboard_arithmetic_currency_and_series(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    add_finance_data(database)
    response = client.get("/api/v1/dashboard?month=2026-08")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "net_worth": "1000.0000",
        "cash_available": "900.0000",
        "income": "3000.0000",
        "spending": "1375.0000",
        "net_cash_flow": "1625.0000",
        "savings_rate": "54.1667",
    }
    assert body["excluded_currencies"] == ["EUR"]
    assert len(body["daily_cash_flow"]) == 31
    assert sum(Decimal(item["amount"]) for item in body["daily_cash_flow"]) == Decimal("1625.0000")


def test_zero_income_savings_rate_is_null(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    body = client.get("/api/v1/dashboard?month=2026-08").json()
    assert body["summary"]["savings_rate"] is None


def test_transaction_pagination_filters_sort_and_search_escaping(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    add_finance_data(database)
    page = client.get("/api/v1/transactions?page=1&page_size=2&sort=amount&direction=asc")
    assert page.status_code == 200
    assert page.json()["total"] == 5
    assert page.json()["pages"] == 3
    filtered = client.get("/api/v1/transactions?kind=expense&search=Market")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    injection = client.get("/api/v1/transactions?search=%25%27%20OR%201%3D1--")
    assert injection.status_code == 200
    assert injection.json()["total"] == 0
    assert client.get("/api/v1/transactions?page_size=101").status_code == 422


def test_settings_categories_and_cross_user_scope(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    updated = client.patch(
        "/api/v1/settings",
        json={"theme": "dark", "currency": "usd"},
        headers=csrf_headers(csrf),
    )
    assert updated.status_code == 200
    assert updated.json()["theme"] == "dark"
    assert updated.json()["currency"] == "USD"
    selection = client.put(
        "/api/v1/categories/selection",
        json={"category_keys": ["housing"]},
        headers=csrf_headers(csrf),
    )
    assert selection.status_code == 200
    by_key = {item["key"]: item for item in selection.json()["categories"]}
    assert by_key["housing"]["enabled"] is True
    assert by_key["other"]["enabled"] is True
    assert by_key["groceries"]["enabled"] is False

    with database.session_factory() as db:
        second = User(
            username="other",
            normalized_username="other",
            email="other@example.com",
            normalized_email="other@example.com",
            password_hash="unused",
        )
        from app.models import UserSettings

        second.settings = UserSettings(currency="USD", timezone="UTC", theme="system")
        db.add(second)
        db.flush()
        db.add(
            Account(
                user_id=second.id,
                name="Private account",
                account_type="depository",
                current_balance=Decimal("999999"),
                currency="USD",
            )
        )
        db.commit()
    accounts = client.get("/api/v1/accounts").json()["accounts"]
    assert all(item["name"] != "Private account" for item in accounts)


def test_manual_account_and_transaction_crud(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)

    account_payload = {
        "name": "Cash checking",
        "official_name": "Primary checking",
        "account_type": "depository",
        "account_subtype": "checking",
        "current_balance": "1250.0000",
        "available_balance": "1200.0000",
        "currency": "usd",
        "mask_last4": "7788",
    }
    assert client.post("/api/v1/accounts", json=account_payload).status_code == 403
    created_account = client.post("/api/v1/accounts", json=account_payload, headers=headers)
    assert created_account.status_code == 201, created_account.text
    account = created_account.json()
    assert account["source_type"] == "manual"
    assert account["currency"] == "USD"
    assert account["mask"] == "•••• 7788"

    updated_account = client.patch(
        f"/api/v1/accounts/{account['id']}",
        json={"current_balance": "1300.0000", "available_balance": None},
        headers=headers,
    )
    assert updated_account.status_code == 200
    assert updated_account.json()["current_balance"] == "1300.0000"
    assert updated_account.json()["available_balance"] is None

    categories = client.get("/api/v1/categories/selection").json()["categories"]
    groceries = next(item for item in categories if item["key"] == "groceries")
    transaction_payload = {
        "account_id": account["id"],
        "category_id": groceries["id"],
        "posted_date": "2026-08-12",
        "merchant": "Corner Market",
        "description": "Groceries",
        "amount": "-42.5000",
        "kind": "expense",
        "pending": False,
        "notes": "Weekly grocery run",
    }
    created_transaction = client.post(
        "/api/v1/transactions", json=transaction_payload, headers=headers
    )
    assert created_transaction.status_code == 201, created_transaction.text
    transaction = created_transaction.json()
    assert transaction["source_type"] == "manual"
    assert transaction["amount"] == "-42.5000"
    assert transaction["notes"] == "Weekly grocery run"

    invalid_sign = client.patch(
        f"/api/v1/transactions/{transaction['id']}",
        json={"amount": "5.0000"},
        headers=headers,
    )
    assert invalid_sign.status_code == 422
    assert invalid_sign.json()["error"]["code"] == "invalid_transaction_amount"

    updated_transaction = client.patch(
        f"/api/v1/transactions/{transaction['id']}",
        json={"merchant": "Neighborhood Market", "amount": "-50.0000", "category_id": None},
        headers=headers,
    )
    assert updated_transaction.status_code == 200
    assert updated_transaction.json()["merchant"] == "Neighborhood Market"
    assert updated_transaction.json()["category"] is None

    dashboard = client.get("/api/v1/dashboard?month=2026-08").json()
    assert dashboard["summary"]["spending"] == "50.0000"
    assert dashboard["summary"]["net_worth"] == "1300.0000"

    deleted_transaction = client.delete(
        f"/api/v1/transactions/{transaction['id']}", headers=headers
    )
    assert deleted_transaction.status_code == 200
    assert deleted_transaction.json() == {"ok": True}
    assert client.get("/api/v1/transactions").json()["total"] == 0

    cascade_candidate = dict(transaction_payload)
    cascade_candidate.update(description="Deleted with account", amount="-3.0000")
    assert (
        client.post("/api/v1/transactions", json=cascade_candidate, headers=headers).status_code
        == 201
    )
    assert client.get("/api/v1/transactions").json()["total"] == 1

    deleted_account = client.delete(f"/api/v1/accounts/{account['id']}", headers=headers)
    assert deleted_account.status_code == 200
    assert deleted_account.json() == {"ok": True}
    assert client.get("/api/v1/accounts").json()["accounts"] == []
    assert client.get("/api/v1/transactions").json()["total"] == 0

    with database.session_factory() as db:
        actions = set(db.scalars(select(AuditEvent.action)).all())
        assert {
            "account.create",
            "account.update",
            "account.delete",
            "transaction.create",
            "transaction.update",
            "transaction.delete",
        }.issubset(actions)


def test_manual_write_scope_and_provider_managed_protection(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    with database.session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert owner is not None
        from app.models import UserSettings

        other = User(
            username="finance-other",
            normalized_username="finance-other",
            email="finance-other@example.com",
            normalized_email="finance-other@example.com",
            password_hash="unused",
            settings=UserSettings(currency="USD", timezone="UTC", theme="system"),
        )
        db.add(other)
        db.flush()
        other_account = Account(
            user_id=other.id,
            name="Other checking",
            account_type="depository",
            source_type="manual",
            current_balance=Decimal("1"),
            currency="USD",
        )
        plaid_account = Account(
            user_id=owner.id,
            name="Future connected account",
            account_type="depository",
            source_type="plaid",
            current_balance=Decimal("100"),
            currency="USD",
            external_id="plaid-account-test",
        )
        db.add_all([other_account, plaid_account])
        db.flush()
        plaid_transaction = Transaction(
            user_id=owner.id,
            account_id=plaid_account.id,
            external_id="plaid-transaction-test",
            posted_date=date(2026, 8, 12),
            description="Provider transaction",
            amount=Decimal("-10"),
            kind="expense",
            source_type="plaid",
            pending=False,
            imported_at=utc_now(),
        )
        db.add(plaid_transaction)
        db.commit()
        other_account_id = other_account.id
        plaid_account_id = plaid_account.id
        plaid_transaction_id = plaid_transaction.id

    cross_user = client.post(
        "/api/v1/transactions",
        json={
            "account_id": other_account_id,
            "posted_date": "2026-08-12",
            "description": "Not mine",
            "amount": "-1.0000",
            "kind": "expense",
        },
        headers=headers,
    )
    assert cross_user.status_code == 404

    managed_patch = client.patch(
        f"/api/v1/accounts/{plaid_account_id}",
        json={"name": "Do not edit"},
        headers=headers,
    )
    assert managed_patch.status_code == 409
    assert managed_patch.json()["error"]["code"] == "account_managed_externally"
    managed_delete = client.delete(f"/api/v1/accounts/{plaid_account_id}", headers=headers)
    assert managed_delete.status_code == 409

    managed_transaction_patch = client.patch(
        f"/api/v1/transactions/{plaid_transaction_id}",
        json={"description": "Do not edit"},
        headers=headers,
    )
    assert managed_transaction_patch.status_code == 409
    assert managed_transaction_patch.json()["error"]["code"] == "transaction_managed_externally"
    managed_transaction_delete = client.delete(
        f"/api/v1/transactions/{plaid_transaction_id}", headers=headers
    )
    assert managed_transaction_delete.status_code == 409
